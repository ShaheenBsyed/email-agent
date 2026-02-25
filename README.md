# Agentic AI Email Bot 🤖📧

An autonomous, serverless AI Email Assistant that polls your Gmail inbox, classifies emails using Large Language Models (OpenAI/Groq), handles complex semantic routing, and dynamically creates Google Workspace structures on the fly. Built on [Modal](https://modal.com/) for a 100% serverless, cron-driven architecture.

## 🌟 Key Features

### 🧠 Zero-Duplicate AI Classification
The bot operates on a 60-second polling architecture (`after:{timestamp}`). Once an email is processed by the AI, it is marked with an internal `AI Processed` label, guaranteeing it is never analyzed twice.

### 🔀 Dynamic Semantic Routing (Action Matrix)
Instead of static regex rules, the bot uses `gpt-4o-mini` (or Groq's Llama models) to semantically understand an email's context and execute specific logic:
- **Social/Promotional**: Immediately marked as read and archived.
- **Accounting**: Automatically forwards the thread and all receipts to your accounting system.
- **Personal/Primary**: Autonomously drafts a natural, contextual reply and attaches it as a Draft to the thread.
- **Misc/Sales/Recruitment**: Leaves it in your Inbox but applies the semantic label.

### 🪄 On-Demand Label Creation
If the AI encounters an email that sits completely outside your established categories (like a highly specific shipping update or a niche business proposition), it will *invent* a concise 1-2 word category and dynamically provision that label directly into your Gmail account in real-time.

### 📂 Automated Drive Architecture
Before any action is taken, the bot dynamically provisions Google Drive folders. It downloads every attachment in your inbox and securely maps them to `Gmail Attachments/{Category}/{Date}-{Sender}-{Filename}`.

### 📜 "Hot-Reloadable" Directives
The AI reads from a mounted `directives/` folder (containing Markdown files of your label schemas and routing rules) on *every single execution cycle*. This means you can update your bot's behavior in plain English mid-deployment without ever changing the source code or redeploying the Docker image.

## 🛠️ Architecture

* **Execution Layer (`execution/`)**: Contains the `modal` python scripts (`gmail_bot.py`), which handle OAuth, Gmail APIs, polling logic, and the core Python execution loop.
* **Orchestration Layer**: The AI Model acts as the orchestrator, deciding which action branch to take based on the raw text.
* **Directive Layer (`directives/`)**: Pure Markdown text files (`gmail_instructions.md`, `gmail_labels.md`) that act as the source-of-truth instructions for the AI on every run.

## 🚀 Getting Started

1. Connect your Google Cloud project and download your `credentials.json` with the required OAuth scopes (Gmail Modify, Drive File).
2. Run `python execution/authenticate_google.py` to generate your `token.json`.
3. Set your `OPENAI_API_KEY` or `GROQ_API_KEY` in your `.env`.
4. Run `python execution/create_secret_json.py` to sync credentials to your Modal Workspace.
5. Deploy the serverless polling architecture to Modal:
   ```bash
   python -m modal deploy execution/gmail_bot.py
   ```
