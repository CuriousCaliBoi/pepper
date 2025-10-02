<div align="center">

# Pepper

</div>

<h3 align="center">
Your Personal AI Assistant
</h3>

<p align="center">
<a href="https://blog.vllm.ai/"><b>Blog</b></a>
</p>

Pepper is a personal AI assistant that proactively works for you. It connects to your Gmail to autonomously summarize important emails and surface critical updates that need your attention, delegating complex tasks to a swarm of workers that handle them seamlessly in the background.



## Setup

First clone the repo:
```bash
git clone --recurse-submodules https://github.com/agentica-org/pepper
```

**Prerequisites:** Install and run the Context Store locally before launching Pepper.


```bash
conda create -n pepper python=3.12 pip -y
conda activate pepper

# First, install our context store Episodic
cd episodic-sdk
pip install -e .[semantic]

# Then, install requirements for Pepper
cd ../pepper
pip install -r requirements.txt
```

followed by:
```bash
episodic serve --port 8000
```

### Configure Environment
1. Copy the environment template:
   ```bash
   cd pepper
   cp env_var.example.sh env_var.sh
   ```

2. Set up Composio (required):
   - Sign in at [composio.dev](https://composio.dev)
   - Create an Project API key
   - Fill in it as `COMPOSIO_API_KEY`
   
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

Open the UI in your browser as prompted:
```
http://localhost:5050/pepper/ui.html
```

If you're in the remote server, vscode should be able to port forward the correct port to your local machine automatically.

**Note:** Press Ctrl+C to stop all services.

## Acknowledgement
This work is done with the [Agentica](https://agentica-project.com/index.html) Team as part of [Berkeley Sky Computing Lab](https://sky.cs.berkeley.edu/). 
