# Modal Setup Instructions for Antigravity


**Goal**: Deploy a serverless webhook to the cloud in 5-10 minutes.


**What You'll Get**: A cloud-hosted webhook that can be called from anywhere (n8n, APIs, browsers, etc.)


---


## Prerequisites


Before starting, you'll need:


1. **Modal Account** - Sign up at https://modal.com (free tier available)
2. **Modal API Token** - You'll get this during setup below


**🔒 Important**: Each user must create their own Modal account and authenticate with their own credentials. API keys are stored locally in `~/.modal.toml` and are **never** included in code files.


---


## Step 1: Install Modal


Ask Antigravity to run:


```bash
pip install modal
```


**Expected Output**: Modal library installed successfully


---


## Step 2: Authenticate with Modal


Ask Antigravity to run:


```bash
python3 -m modal setup
```


**What Happens**:
- A browser window will open
- You'll be asked to log in to Modal
- You'll authorize the connection
- Modal will save your credentials locally


**Expected Output**:
```
✓ Initialized token.
```


---


## Step 3: Create Your First Webhook


Create a file called `hello_webhook.py`:


```python
import modal


app = modal.App("hello-webhook")


# Define the container image with dependencies
image = modal.Image.debian_slim().pip_install("fastapi")


@app.function(image=image)
@modal.asgi_app()
def webhook():
   from fastapi import FastAPI, Query
  
   web_app = FastAPI()
  
   @web_app.get("/")
   @web_app.post("/")
   def hello(name: str = Query(default="World")):
       return {
           "message": f"Hi {name}",
           "status": "success"
       }
  
   return web_app
```


---


## Step 4: Deploy to the Cloud


Ask Antigravity to run:


```bash
python3 -m modal deploy hello_webhook.py
```


**Expected Output**:
```
✓ Created objects.
├── 🔨 Created mount /path/to/hello_webhook.py
└── 🔨 Created web function webhook => https://YOUR-USERNAME--hello-webhook-webhook.modal.run
✓ App deployed! 🎉
```


**Copy your webhook URL** - you'll need it for testing!


---


## Step 5: Test Your Webhook


Ask Antigravity to run (replace with your actual URL):


```bash
curl "https://YOUR-USERNAME--hello-webhook-webhook.modal.run?name=Test"
```


**Expected Output**:
```json
{"message":"Hi Test","status":"success"}
```


**🎉 Success!** Your webhook is now live in the cloud!


---


## Common Issues & Solutions


### Issue 1: `ModuleNotFoundError: No module named 'fastapi'`


**Problem**: FastAPI not installed in the Modal container


**Solution**: Make sure your image includes `.pip_install("fastapi")`:
```python
image = modal.Image.debian_slim().pip_install("fastapi")
```


---


### Issue 2: `@modal.web_endpoint is deprecated`


**Problem**: Using old decorator syntax


**Solution**: Use `@modal.asgi_app()` instead:
```python
@app.function(image=image)
@modal.asgi_app()  # ✅ Correct
def webhook():
   # ...
```


---


### Issue 3: `TypeError: webhook() takes 0 positional arguments but 3 were given`


**Problem**: ASGI app function shouldn't have parameters


**Solution**: The function that returns the FastAPI app should have no parameters:
```python
@modal.asgi_app()
def webhook():  # ✅ No parameters!
   from fastapi import FastAPI
   web_app = FastAPI()
  
   @web_app.get("/")
   def endpoint(name: str = Query(default="World")):  # ✅ Parameters go here
       return {"message": f"Hi {name}"}
  
   return web_app
```


---


### Issue 4: Timeout Issues with n8n


**Problem**: Long-running tasks cause n8n to timeout


**Solution**: Use `.spawn()` to return immediately:


```python
import modal


app = modal.App("async-webhook")
image = modal.Image.debian_slim().pip_install("fastapi")


@app.function(image=image, timeout=1800)  # 30 minutes
def long_running_task(city: str):
   """Your long-running task here"""
   import time
   time.sleep(10)  # Simulate long work
   return {"status": "completed", "city": city}


@app.function(image=image)
@modal.asgi_app()
def webhook():
   from fastapi import FastAPI, Query
  
   web_app = FastAPI()
  
   @web_app.post("/process")
   def trigger_task(city: str = Query(default="Toronto")):
       # Spawn in background - returns immediately!
       call = long_running_task.spawn(city=city)
      
       return {
           "status": "started",
           "job_id": call.object_id,
           "message": f"Processing {city} in the background"
       }
  
   return web_app
```


**Key Point**: `.spawn()` starts the task and returns immediately with a job ID. Perfect for n8n!


---


## Adding a Schedule (Cron Job)


Want your function to run automatically? Add a schedule:


```python
import modal
from datetime import datetime


app = modal.App("scheduled-task")
image = modal.Image.debian_slim()


@app.function(
   image=image,
   schedule=modal.Cron("0 9 * * *")  # Every day at 9 AM
)
def daily_report():
   print(f"Running daily report at {datetime.now()}")
   # Your code here
   return {"status": "completed"}
```


**Common Schedules**:
- Every hour: `"0 * * * *"`
- Every day at 9 AM: `"0 9 * * *"`
- Every Monday at 9 AM: `"0 9 * * MON"`
- Every 15 minutes: `"*/15 * * * *"`


**Deploy**: `python3 -m modal deploy scheduled_task.py`


**View logs**: `python3 -m modal app logs scheduled-task`


---


## Security Best Practices


### Adding API Key Authentication


```python
from fastapi import FastAPI, Header, HTTPException
import os


@web_app.post("/secure")
def secure_endpoint(
   data: str = Query(default="test"),
   api_key: str = Header(...)
):
   # Check API key
   if api_key != os.environ.get("MY_API_KEY"):
       raise HTTPException(status_code=401, detail="Invalid API key")
  
   # Your code here
   return {"status": "authenticated", "data": data}
```


### Using Modal Secrets


1. Go to https://modal.com/secrets
2. Create a new secret (e.g., "my-api-keys")
3. Add your key-value pairs
4. Use in your function:


```python
secret = modal.Secret.from_name("my-api-keys")


@app.function(image=image, secrets=[secret])
def my_function():
   import os
   api_key = os.environ["MY_API_KEY"]
   # Use api_key here
```


---


## Costs & Limits


**Free Tier** (as of 2024):
- $30/month in free credits
- Good for testing and small projects


**Typical Costs**:
- Simple webhook: ~$0.0001 per request
- 1000 requests/day ≈ $3/month


**Limits**:
- Default timeout: 300 seconds (5 minutes)
- Max timeout: 86400 seconds (24 hours)
- Default memory: 128MB
- Max memory: 32GB


---


## Essential Commands


```bash
# Setup
pip install modal
python3 -m modal setup


# Deploy (runs continuously)
python3 -m modal deploy app.py


# Run once
python3 -m modal run app.py


# View logs
python3 -m modal app logs app-name


# List apps
python3 -m modal app list
```


---


## Next Steps


✅ **You now have a working webhook!**


Want to do more advanced things?


- 🚀 **Multi-agent systems** - See [ADVANCED.md](ADVANCED.md)
- 🎯 **Queues & event processing** - See [ADVANCED.md](ADVANCED.md)
- 🤖 **Browser automation** - See [ADVANCED.md](ADVANCED.md) (can be brittle!)
- 💪 **GPU/Memory configuration** - See [ADVANCED.md](ADVANCED.md)
- 📊 **Manual/programmatic calls** - See [ADVANCED.md](ADVANCED.md)


---


## How Credentials Work


**Your code is safe to share!** Here's why:


- **Credentials stored locally**: `~/.modal.toml` on your computer
- **Never in code**: API keys are NOT in `.py` files
- **Each user has their own**: When someone uses your code, they run `python3 -m modal setup` and get their own credentials


**What NOT to share**:
- `~/.modal.toml` - Your Modal credentials
- `.env` files - Environment variables


**What IS safe to share**:
- All `.py` code files
- All `.md` documentation files
- Example files


---


**🎉 That's it! You're ready to deploy serverless Python to the cloud!**


For advanced patterns, see [ADVANCED.md](ADVANCED.md)
