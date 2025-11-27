# Setup and Deployment Guide

### 1. Create Virtual Environment

```bash
python -m venv venv
```

### 2. Activate Virtual Environment

```bash
source venv/bin/activate
```

### 3. Install Dependencies

*(some packages may require manual installation if errors occur)*

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

```bash
nano .env
```

---

# Database Setup (MySQL)

### 1. Install MySQL (if not installed)

```bash
sudo apt update
sudo apt install mysql-server
```

### 2. Verify MySQL Service

```bash
systemctl status mysql
```

### 3. Access MySQL as root

```bash
sudo mysql
```

### 4. Create User and Database

```sql
CREATE USER 'admin1'@'localhost' IDENTIFIED BY 'pass_test1';
CREATE DATABASE poc_paywall;
GRANT ALL PRIVILEGES ON poc_paywall.* TO 'admin1'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

---

# Application Server

### Development Mode (port 8000)

```bash
uvicorn main:app --reload --port 8000
```

---

# Production Setup (Cloudflared Reverse Tunnel)

### 1. Install Cloudflared (if not installed)

```bash
sudo apt update
sudo apt install cloudflared
```

### 2. Verify Cloudflared Service

```bash
systemctl status cloudflared
```

### 3. Edit Cloudflared Configuration

```bash
sudo nano /etc/cloudflared/config.yml
```

Example:

```yaml
tunnel: 11111111-1111-1111-1111-111111111111
credentials-file: /etc/cloudflared/11111111-1111-1111-1111-111111111111.json

ingress:
  - hostname: ssh.mysupersite.com
    service: ssh://localhost:22

  # - hostname: mysupersite.com
  #   service: https://localhost:443

  - hostname: app.mysupersite.com
    service: http://localhost:80

  - service: http_status:404

no-autoupdate: true
prefer-ipv4: true
```

### 4. Run Application in Production

Run in foreground:
```bash
sudo env "PATH=$PATH" uvicorn main:app --host 0.0.0.0 --port 80
```

Run in background:
```bash
sudo nohup env "PATH=$PATH" uvicorn main:app --host 0.0.0.0 --port 80 > app.log 2>&1 &
```

Search process in background:
```bash
ps aux | grep uvicorn
```

Kill process in background:
```bash
sudo kill -9 <PID>
```

---

# Accessing the Application

### From LAN

Get server IP:

```bash
hostname -I
```

Open in browser:

```
http://<SERVER_IP>:<PORT>
```

### From Internet (Cloudflared)

Open the configured hostname (e.g., `https://app.mysupersite.com`).


---
Dev. by: tobiasrimoli@protonmail.com