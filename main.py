from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form, Request, Path
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db, engine
from models import Base, Conversion, Payment
from utils import convert_docx_to_pdf, check_usdt_payment, log_metric
from config import settings
import aiofiles
import os
import uuid
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(SlowAPIMiddleware)  # Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    log_metric("page_visit")
    return templates.TemplateResponse("index.html", {"request": request})

from fastapi.responses import JSONResponse

@app.post("/upload")
@limiter.limit("10/minute")  # Límite básico por IP
async def upload_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        if not file.filename.endswith(".docx"):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Only .docx files allowed"}
            )

        docx_path = f"uploads/{file.filename}"
        pdf_filename = f"{uuid.uuid4()}.pdf"
        pdf_path = f"pdfs/{pdf_filename}"
        
        os.makedirs("uploads", exist_ok=True)
        os.makedirs("pdfs", exist_ok=True)

        async with aiofiles.open(docx_path, "wb") as f:
            await f.write(await file.read())

        page_count = convert_docx_to_pdf(docx_path, pdf_path)
        conversion_uuid = str(uuid.uuid4())
        conversion = Conversion(
            uuid=conversion_uuid,
            original_filename=file.filename,
            pdf_filename=pdf_filename,
            page_count=page_count
        )
        db.add(conversion)
        db.commit()
        log_metric("conversion_completed", page_count)

        response_data = {
            "success": True,
            "message": "File converted successfully",
            "filename": pdf_filename,
            "conversion_uuid": conversion_uuid,
            "page_count": page_count,
            "requires_payment": page_count > 50
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Error processing file: {str(e)}"}
        )

@app.get("/download/{conversion_uuid}")
async def download_file(conversion_uuid: str = Path(..., description="The UUID of the conversion"), db: Session = Depends(get_db)):
    # First check if the conversion exists in the database
    conversion = db.query(Conversion).filter(Conversion.uuid == conversion_uuid).first()
    if not conversion:
        raise HTTPException(status_code=404, detail="Conversion not found in database")
    
    # Check if the file exists in the filesystem
    file_path = os.path.join("pdfs", conversion.pdf_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")
    
    # Check payment status
    payment = db.query(Payment).filter(
        Payment.conversion_id == conversion.id,
        Payment.status == "completed"
    ).first()
    
    # For files over 50 pages, payment is required
    if conversion.page_count > 50 and not payment:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment required",
                "conversion_uuid": conversion.uuid,
                "page_count": conversion.page_count,
                "requires_payment": True
            }
        )
    
    # If we get here, either payment is not required or payment was successful
    return FileResponse(
        path=file_path,
        filename=conversion.original_filename.replace('.docx', '.pdf'),
        media_type='application/pdf',
        headers={"Content-Disposition": f"attachment; filename={conversion.original_filename.replace('.docx', '.pdf')}"}
    )

@app.post("/pay")
async def pay(conversion_uuid: str = Form(...), method: str = Form(...), tx_hash: str = Form(None), db: Session = Depends(get_db)):
    conversion = db.query(Conversion).filter(Conversion.uuid == conversion_uuid).first()
    if not conversion:
        raise HTTPException(status_code=404, detail="Conversion not found")

    if method == "usdt":
        if not check_usdt_payment(tx_hash):
            raise HTTPException(status_code=400, detail="Payment not verified")
        amount = settings.min_usdt_payment
    elif method == "credit_card":
        # Simular pago aprobado
        amount = 5.0
    else:
        raise HTTPException(status_code=400, detail="Invalid method")

    payment = Payment(conversion_id=conversion.id, method=method, amount=amount, tx_hash=tx_hash, status="completed")
    db.add(payment)
    conversion.paid = True
    db.commit()
    log_metric("payment_completed", amount)
    return FileResponse(f"pdfs/{conversion.pdf_filename}", media_type="application/pdf", filename=conversion.pdf_filename)

@app.get("/admin", response_class=HTMLResponse)
@app.post("/admin", response_class=HTMLResponse)
async def admin_panel(
    request: Request,
    username: str = Form(None),
    password: str = Form(None),
    db: Session = Depends(get_db)
):
    # Check if this is a POST request with credentials
    if request.method == "POST":
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password are required")
        if username != settings.admin_username or not verify_password(password, settings.admin_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # For GET requests, show login form
    if request.method == "GET":
        return templates.TemplateResponse("login.html", {"request": request})
    
    # If we get here, it's a POST with valid credentials
    metrics = db.query(Metric).all()
    users_count = db.query(User).count()
    conversions_count = db.query(Conversion).count()
    payments_total = db.query(Payment).filter(Payment.status == "completed").count()
    
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "metrics": metrics,
            "users": users_count,
            "conversions": conversions_count,
            "payments": payments_total
        }
    )