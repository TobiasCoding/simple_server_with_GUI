import os
import bcrypt
import jwt
from datetime import datetime, timedelta
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from web3 import Web3
from config import settings
from models import Metric
from database import SessionLocal

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_jwt_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_expiration_hours)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)

def convert_docx_to_pdf(docx_path: str, pdf_path: str) -> int:
    # Convert DOCX to PDF using unoconv
    import subprocess
    
    # First, get the page count using unoconv
    try:
        # Try to get page count using unoconv and pdftk
        temp_pdf = "/tmp/temp_convert.pdf"
        subprocess.run(["unoconv", "-f", "pdf", "-o", temp_pdf, docx_path], check=True)
        
        # Get page count using pdftk
        result = subprocess.run(
            ["pdftk", temp_pdf, "dump_data"], 
            capture_output=True, 
            text=True
        )
        
        # Parse the page count
        page_count = 1
        for line in result.stdout.split('\n'):
            if line.startswith('NumberOfPages:'):
                page_count = int(line.split(':')[1].strip())
                break
                
        # Clean up temp file
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
            
    except Exception as e:
        print(f"Error getting page count: {e}")
        # Fallback to basic conversion if unoconv fails
        doc = Document(docx_path)
        text = "\n".join([para.text for para in doc.paragraphs])
        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        y = height - 50
        for line in text.split('\n'):
            if y < 50:
                c.showPage()
                y = height - 50
            c.drawString(50, y, line)
            y -= 15
        c.save()
        # Estimate pages (approx. 300 words per page)
        word_count = len(text.split())
        page_count = max(1, word_count // 300)
    
    return page_count

def check_usdt_payment(tx_hash: str) -> bool:
    w3 = Web3(Web3.HTTPProvider(settings.eth_rpc_url))
    contract = w3.eth.contract(address=settings.usdt_contract_address, abi=[...])  # ABI simplificado para transfer
    tx = w3.eth.get_transaction(tx_hash)
    return tx['to'] == settings.wallet_address and tx['value'] >= settings.min_usdt_payment * 10**6  # USDT decimals

def log_metric(event: str, value: float = 1):
    db = SessionLocal()
    metric = Metric(event=event, value=value)
    db.add(metric)
    db.commit()
    db.close()