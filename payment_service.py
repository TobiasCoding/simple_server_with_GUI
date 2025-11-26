import os
import stripe
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, Union
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import Payment, PaymentStatus, PaymentMethod, Conversion, User
from config import settings
import coinbase_commerce
from coinbase_commerce.client import Client as CoinbaseClient
from coinbase_commerce.webhook import WebhookSignature, WebhookInvalidPayload, WebhookInvalidSignature

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize payment providers
def init_payment_providers():
    """Initialize payment provider clients"""
    # Stripe
    stripe.api_key = settings.stripe_secret_key
    
    # Coinbase Commerce
    coinbase_client = None
    if settings.coinbase_api_key:
        coinbase_client = CoinbaseClient(api_key=settings.coinbase_api_key)
    
    return {
        'stripe': stripe,
        'coinbase': coinbase_client
    }

payment_clients = init_payment_providers()

class PaymentService:
    """Service for handling payment processing"""
    
    @staticmethod
    def calculate_price(page_count: int) -> float:
        """Calculate price based on page count and pricing settings"""
        if page_count <= settings.free_page_limit:
            return 0.0
        
        # Calculate price for pages beyond the free limit
        extra_pages = page_count - settings.free_page_limit
        return round(extra_pages * settings.price_per_page, 2)
    
    @staticmethod
    def create_payment_intent(
        db: Session, 
        conversion: Conversion, 
        payment_method: str,
        user: Optional[User] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a payment intent with the selected payment method"""
        if conversion.is_paid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This conversion has already been paid for"
            )
        
        amount = PaymentService.calculate_price(conversion.page_count)
        if amount <= 0:
            # If no payment is needed, mark as paid and return
            conversion.is_paid = True
            db.commit()
            return {"status": "success", "paid": True, "amount": 0.0}
        
        # Create payment record
        payment = Payment(
            user_id=user.id if user else None,
            conversion_id=conversion.id,
            payment_method=PaymentMethod(payment_method),
            amount=amount,
            amount_usd=amount,  # Assuming USD for now, can be converted for other currencies
            currency='USD',
            status=PaymentStatus.PENDING,
            expires_at=datetime.utcnow() + timedelta(hours=24)  # Payment expires in 24 hours
        )
        
        db.add(payment)
        db.commit()
        db.refresh(payment)
        
        try:
            if payment_method == PaymentMethod.CREDIT_CARD:
                return PaymentService._process_credit_card_payment(db, payment, conversion, metadata)
            elif payment_method in [PaymentMethod.BTC, PaymentMethod.ETH, PaymentMethod.USDT, PaymentMethod.OTHER_CRYPTO]:
                return PaymentService._process_crypto_payment(db, payment, conversion, metadata)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported payment method: {payment_method}"
                )
        except Exception as e:
            logger.error(f"Error creating payment intent: {str(e)}")
            payment.status = PaymentStatus.FAILED
            payment.provider_data = {"error": str(e)}
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error processing payment: {str(e)}"
            )
    
    @staticmethod
    def _process_credit_card_payment(
        db: Session, 
        payment: Payment, 
        conversion: Conversion,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process credit card payment using Stripe"""
        try:
            # Create a Stripe PaymentIntent
            intent = payment_clients['stripe'].PaymentIntent.create(
                amount=int(payment.amount * 100),  # Amount in cents
                currency=payment.currency.lower(),
                metadata={
                    'conversion_id': str(conversion.id),
                    'payment_id': str(payment.id),
                    'user_id': str(payment.user_id) if payment.user_id else 'anonymous',
                    **(metadata or {})
                },
                description=f"Payment for {conversion.original_filename} ({conversion.page_count} pages)",
                receipt_email=metadata.get('email') if metadata else None,
                automatic_payment_methods={
                    'enabled': True,
                },
            )
            
            # Update payment record with Stripe details
            payment.provider = 'stripe'
            payment.provider_payment_id = intent.id
            payment.provider_data = intent.to_dict()
            db.commit()
            
            return {
                'payment_id': payment.id,
                'client_secret': intent.client_secret,
                'publishable_key': settings.stripe_public_key,
                'amount': payment.amount,
                'currency': payment.currency,
                'status': payment.status,
                'requires_action': True,
                'payment_method_types': ['card']
            }
            
        except Exception as e:
            logger.error(f"Stripe payment error: {str(e)}")
            raise
    
    @staticmethod
    def _process_crypto_payment(
        db: Session, 
        payment: Payment, 
        conversion: Conversion,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process cryptocurrency payment using Coinbase Commerce"""
        if not payment_clients['coinbase']:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cryptocurrency payments are not configured"
            )
        
        try:
            # Create a charge on Coinbase Commerce
            charge_data = {
                'name': f"PDF Conversion: {conversion.original_filename}",
                'description': f"Payment for {conversion.page_count} page document conversion",
                'pricing_type': 'fixed_price',
                'local_price': {
                    'amount': f"{payment.amount:.2f}",
                    'currency': payment.currency
                },
                'metadata': {
                    'conversion_id': str(conversion.id),
                    'payment_id': str(payment.id),
                    'user_id': str(payment.user_id) if payment.user_id else 'anonymous',
                    **(metadata or {})
                },
                'redirect_url': f"{settings.app_url}/payment/complete",
                'cancel_url': f"{settings.app_url}/payment/cancel"
            }
            
            charge = payment_clients['coinbase'].charge.create(**charge_data)
            
            # Update payment record with Coinbase details
            payment.provider = 'coinbase'
            payment.provider_payment_id = charge.id
            payment.crypto_address = charge.addresses.get('bitcoin') or charge.addresses.get('ethereum')
            payment.crypto_amount = float(charge.pricing['local']['amount'])
            payment.provider_data = charge
            db.commit()
            
            return {
                'payment_id': payment.id,
                'checkout_url': charge.hosted_url,
                'crypto_address': payment.crypto_address,
                'crypto_amount': payment.crypto_amount,
                'currency': payment.currency,
                'status': payment.status,
                'expires_at': payment.expires_at.isoformat() if payment.expires_at else None
            }
            
        except Exception as e:
            logger.error(f"Coinbase payment error: {str(e)}")
            raise
    
    @staticmethod
    def handle_webhook(
        db: Session, 
        provider: str, 
        payload: bytes, 
        signature: Optional[str] = None
    ) -> Dict[str, Any]:
        """Handle payment webhook from payment providers"""
        try:
            if provider == 'stripe':
                return PaymentService._handle_stripe_webhook(db, payload, signature)
            elif provider == 'coinbase':
                return PaymentService._handle_coinbase_webhook(db, payload, signature)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported payment provider: {provider}"
                )
        except Exception as e:
            logger.error(f"Webhook error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error processing webhook: {str(e)}"
            )
    
    @staticmethod
    def _handle_stripe_webhook(
        db: Session, 
        payload: bytes, 
        signature: str
    ) -> Dict[str, Any]:
        """Handle Stripe webhook events"""
        try:
            event = stripe.Webhook.construct_event(
                payload, 
                signature, 
                settings.stripe_webhook_secret
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
        except stripe.error.SignatureVerificationError as e:
            raise HTTPException(status_code=400, detail=f"Invalid signature: {str(e)}")
        
        # Handle the event
        if event['type'] == 'payment_intent.succeeded':
            payment_intent = event['data']['object']
            return PaymentService._process_successful_payment(
                db, 
                payment_intent.metadata.get('payment_id'),
                provider_data=payment_intent
            )
        
        # Handle other event types as needed
        
        return {'status': 'success', 'event': event['type']}
    
    @staticmethod
    def _handle_coinbase_webhook(
        db: Session, 
        payload: bytes, 
        signature: str
    ) -> Dict[str, Any]:
        """Handle Coinbase Commerce webhook events"""
        try:
            # Verify the webhook signature
            request_data = json.loads(payload)
            
            try:
                WebhookSignature.verify_payload(
                    payload,
                    signature,
                    settings.coinbase_webhook_secret
                )
            except (WebhookInvalidPayload, WebhookInvalidSignature) as e:
                raise HTTPException(status_code=400, detail=f"Webhook verification failed: {str(e)}")
            
            event = request_data.get('event')
            if not event:
                raise HTTPException(status_code=400, detail="No event in payload")
            
            # Handle the event
            if event['type'] == 'charge:confirmed' or event['type'] == 'charge:resolved':
                charge = event['data']
                return PaymentService._process_successful_payment(
                    db,
                    charge['metadata'].get('payment_id'),
                    provider_data=charge
                )
            
            return {'status': 'success', 'event': event['type']}
            
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    @staticmethod
    def _process_successful_payment(
        db: Session, 
        payment_id: str,
        provider_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Update payment and conversion status after successful payment"""
        if not payment_id:
            raise HTTPException(status_code=400, detail="No payment ID provided")
        
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        
        # Update payment status
        payment.status = PaymentStatus.COMPLETED
        payment.paid_at = datetime.utcnow()
        payment.updated_at = datetime.utcnow()
        
        if provider_data:
            payment.provider_data = provider_data
        
        # Update conversion status
        conversion = db.query(Conversion).filter(Conversion.id == payment.conversion_id).first()
        if conversion:
            conversion.is_paid = True
            conversion.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            'status': 'success',
            'payment_id': payment.id,
            'conversion_id': payment.conversion_id,
            'paid': True
        }
    
    @staticmethod
    def get_payment_status(
        db: Session, 
        payment_id: int
    ) -> Dict[str, Any]:
        """Get the status of a payment"""
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        
        # If payment is completed, return the status
        if payment.status == PaymentStatus.COMPLETED:
            return {
                'status': 'completed',
                'paid': True,
                'payment_id': payment.id,
                'conversion_id': payment.conversion_id,
                'amount': payment.amount,
                'currency': payment.currency,
                'paid_at': payment.paid_at.isoformat() if payment.paid_at else None
            }
        
        # For pending payments, check with the provider for updates
        try:
            if payment.provider == 'stripe':
                intent = stripe.PaymentIntent.retrieve(payment.provider_payment_id)
                if intent.status == 'succeeded':
                    return PaymentService._process_successful_payment(
                        db, payment_id, intent
                    )
            
            elif payment.provider == 'coinbase':
                charge = payment_clients['coinbase'].charge.retrieve(payment.provider_payment_id)
                if charge['status'] in ['CONFIRMED', 'RESOLVED']:
                    return PaymentService._process_successful_payment(
                        db, payment_id, charge
                    )
        except Exception as e:
            logger.error(f"Error checking payment status: {str(e)}")
        
        # Return current status
        return {
            'status': payment.status,
            'paid': payment.status == PaymentStatus.COMPLETED,
            'payment_id': payment.id,
            'conversion_id': payment.conversion_id,
            'amount': payment.amount,
            'currency': payment.currency,
            'expires_at': payment.expires_at.isoformat() if payment.expires_at else None
        }
