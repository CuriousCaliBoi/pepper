# Pepper

Personal AI assistant for managing tasks and communications.

**Prerequisites:** Run the Context Store locally before launching Pepper.

```bash
cd episodic-sdk
pip install -r requirements.txt
```

followed by
```bash
episodic serve --port 8000
```

## Setup

### Install Dependencies
```bash
conda create -n pepper python=3.12 pip -y
conda activate pepper
pip install -r requirements.txt
```

### Configure Environment
1. Copy the environment template:
   ```bash
   cd pepper
   cp env_var.example.sh env_var.sh
   ```

2. Set up Composio (required for Gmail):
   - Sign in at [composio.dev](https://composio.dev)
   - Create an API key
   - Set up Gmail integration and get your auth config ID
   - Fill in `COMPOSIO_API_KEY`
   
3. Fill in `OPENAI_API_KEY` (required)

4. Load environment variables:
   ```bash
   source env_var.sh
   ```

5. Login your Gmail account and grant access [Only for the first time]:

   ```bash
   python -m pepper.services.email_service
   ```
   If you see the message "Please authorize Gmail by visiting: <url>", open the url in your browser and grant access.
   If you see the message "✅ Trigger subscribed successfully.", you're good to go. Ctrl+C to stop the process.

## Running Pepper

Launch all services (The first time you run this, it'll take a while to build your profile, approximately 1 minute):
```bash
python -m pepper.launch_pepper
```

Open the UI in your browser:
```
http://localhost:5050/pepper/ui.html
```

If you're in the remote server, vscode should be able to port forward the correct port to your local machine automatically.

**Note:** Press Ctrl+C to stop all services.