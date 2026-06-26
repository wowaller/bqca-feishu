# Feishu Conversational Analytics Bot (BQCA Integration)

This project connects a **Feishu (Lark) Chatbot** directly to an **existing Google Cloud BigQuery Conversational Analytics (BQCA) service**. 

Using this bot, users can ask natural language questions about their BigQuery datasets directly in Feishu (1-on-1 or by @-mentioning the bot in groups) and receive high-quality data insights, native interactive tables, **automatically rendered visualization charts**, and the generated SQL queries in beautifully formatted cards.

The bot operates over Feishu's **WebSocket (Stream Mode) connection**, meaning it runs completely securely without requiring a public HTTPS endpoint, domains, SSL certificates, or local tunnels (like ngrok).

---

## 1. Project Structure

```
bqca-feishu/
├── config.py          # Loads Feishu and Google Cloud environment configurations
├── agent.py           # Bridges to the GCP geminidataanalytics (BQCA) API & parses response streams
├── bot.py             # Feishu WebSocket client, event listener, and async card assembler
├── chart_renderer.py  # Renders BQCA vega_config specs into premium Matplotlib PNG charts
├── Dockerfile         # Containerizes the application for seamless Cloud Run deployment
└── requirements.txt   # Python package dependencies
```

---

## 2. Prerequisites & Setup

### Step 2.1: Feishu App Setup
1. Go to the [Feishu Open Platform Console](https://open.feishu.cn/app?lang=zh-CN).
2. Create a **Custom App** and click **Enable Bot** under *App Capabilities > Bot*.
3. Go to *Development Configuration > Event Subscriptions* and switch **Configuration Mode** to **Stream Mode (WebSocket)**.
4. Add the following event:
   * `im.message.receive_v1` (Receive Message v1)
5. Go to *Development Configuration > Permission Management* and add the following scopes:
   * `im:message` (Receive and send messages in chats)
   * `im:message.group_at_msg` (Receive messages that @-mention the bot in group chats)
   * `im:chat` (Acquire chat group information)
   * `im:resource:upload` or `im:resource` (Upload images, videos, and files — **Critical for chart visualization!**)
6. Go to *Credentials & Basic Info* and copy your **App ID** and **App Secret**.
7. Go to *Version Management & Release*, create a new version, and submit it for release. (Enterprise self-built apps are approved immediately).

### Step 2.2: Google Cloud Setup
1. Ensure the **Data Analytics API with Gemini** (`geminidataanalytics.googleapis.com`) is enabled in your Google Cloud project.
2. In the Google Cloud Console, navigate to **BigQuery Studio** and configure/open your **Conversational Analytics Agent (Configuration)**.
3. Copy the **Configuration ID** (or Agent ID) of the configuration you want to connect (e.g., `agent_xxxx-xxxx-xxxx-xxxx`).
4. Ensure the environment where this bot is running is authenticated with GCP (e.g., via Application Default Credentials: `gcloud auth application-default login`). Your GCP identity needs the **Gemini Data Analytics User** and **BigQuery User** roles.

---

## 3. Local Installation & Run

You can run this bot locally on your machine for development and testing.

1. **Set up a Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**:
   Set the following environment variables in your terminal:
   ```bash
   export FEISHU_APP_ID="your-feishu-app-id"
   export FEISHU_APP_SECRET="your-feishu-app-secret"
   export GCP_PROJECT="your-gcp-project-id"
   export BQCA_CONFIG_ID="your-bqca-configuration-id"
   ```

3. **Start the Bot**:
   ```bash
   python bot.py
   ```
   You will see `Starting Feishu WebSocket Bot Listener...`. Your bot is now online and listening to messages in real-time!

---

## 4. Production Deployment on Google Cloud Run

For 24/7 production operation, deploying the bot as a containerized service on **Google Cloud Run** is highly recommended. It provides a serverless, low-maintenance environment.

### Deployment Walkthrough

#### Step 1: Create a Dedicated Service Account
Create a secure identity for the bot to run under in your GCP project:
```bash
gcloud iam service-accounts create bqca-feishu-sa \
    --description="Service Account for Feishu BQCA Bot" \
    --display-name="BQCA Feishu Bot SA"
```

#### Step 2: Grant IAM Roles to the Service Account
Grant the Service Account permission to call the BQCA API:
```bash
gcloud projects add-iam-policy-binding your-gcp-project-id \
    --member="serviceAccount:bqca-feishu-sa@your-gcp-project-id.iam.gserviceaccount.com" \
    --role="roles/geminidataanalytics.user"
```

#### Step 3: Build the Container Image via Cloud Build
Run this command from the project root directory to package the code and push it to Google Container Registry (GCR) in the cloud:
```bash
gcloud builds submit --tag gcr.io/your-gcp-project-id/bqca-feishu-bot
```

#### Step 4: Deploy to Cloud Run (Service Mode)
Deploy the container with optimized settings for long-lived WebSocket connections (locking to exactly 1 instance and allocating continuous CPU):
```bash
gcloud run deploy bqca-feishu-bot \
    --image=gcr.io/your-gcp-project-id/bqca-feishu-bot \
    --platform=managed \
    --region=us-central1 \
    --service-account="bqca-feishu-sa@your-gcp-project-id.iam.gserviceaccount.com" \
    --min-instances=1 \
    --max-instances=1 \
    --cpu=always \
    --no-allow-unauthenticated \
    --set-env-vars="FEISHU_APP_ID=your-feishu-app-id,FEISHU_APP_SECRET=your-feishu-app-secret,GCP_PROJECT=your-gcp-project-id,BQCA_CONFIG_ID=your-bqca-configuration-id"
```

*Note: Cloud Run Services require the container to bind to a port during startup. The application automatically starts a lightweight, background daemon HTTP server on port 8080 to satisfy Cloud Run's required startup probe without blocking the main WebSocket handler.*

---

## 5. Key Architecture Features

* **Stateful Conversations**: The bot maps the Feishu `chat_id` as the BQCA `conversation_id`. Dialogue context is kept seamlessly in the cloud, allowing natural follow-up questions (e.g. *"Show top 5 brands"* followed by *"What is their net profit trend?"*).
* **Asynchronous Multi-Threaded Processing**: Spawns independent worker threads (`process_message_async`) for heavy BQCA queries, allowing the main listener to acknowledge Feishu event frames in under 1ms. This prevents Feishu network timeouts and eliminates duplicate card replies.
* **Over-the-Air Chart Rendering & Uploads**: Automatically extracts BQCA `vega_config` structural chart data, renders high-fidelity Matplotlib charts offline, uploads them on-the-fly to Feishu's media storage, and injects them as native card images.
* **Automatic File Cleanups**: Local temporary chart files are deleted instantly from the server once uploaded, preserving disk health.
* **Stale Event Time Guard**: Calculates the age of incoming events using the `create_time` header. If a message is older than 5 minutes, it is discarded, preventing historical retries from previous server sessions from spamming the user.
* **Interactive Card UI (Schema 2.0)**:
  * **Insights Body**: Synthesized AI markdown analysis.
  * **Native Interactive Tables**: Elegant, scrollable tables representing query results.
  * **📊 Data Visualization**: Beautiful high-res charts showing comparisons or trends (click to zoom/preview).
  * **Collapsible SQL Panel**: A foldout showing the exact generated BigQuery SQL code.
  * **Smart Follow-ups**: Quick-click suggested follow-up prompts.

---

## 6. Common Feishu Troubleshooting & Gotchas

To ensure a smooth hand-off, please review these common configuration pitfalls:

### Gotcha 1: The Bot does not respond in Group Chats
* **Reason 1: Not @-mentioned properly**. In Feishu, typing `@BotName` as plain text does not trigger an event. Users **must** type `@` and select the bot from the popup menu so that it becomes a blue, formatted mention card.
* **Reason 2: Bot is not in the group**. You must manually add the bot to the group. Open the Group Settings > Add Bot, and select your bot.
* **Reason 3: Missing group scope**. Ensure the app has the `im:message.group_at_msg` scope enabled in the Feishu console, and that you have released a new version of the app after adding it.

### Gotcha 2: Charts do not appear in the card (Text-only fallback)
* **Reason 1: Missing Upload Permission**. Rendering charts offline requires the bot to upload the rendered PNG to Feishu's media servers. This requires the **`im:resource:upload`** or **`im:resource`** permission scope. Ensure this scope is enabled and released.
* **Reason 2: BQCA Model Decision**. The Gemini model driving BQCA dynamically decides whether a chart is helpful. For simple questions or counts, it may return text-only insights. Try asking a comparison or trend question (e.g., *"Show monthly sales trends..."*) to force BQCA to generate a chart.

### Gotcha 3: Users cannot find the Bot in search
* **Reason: Availability Range (可用范围) is restricted**. When publishing a new version of the Feishu App, ensure the **Availability Range** is set to **"All Staff"** (或包含测试人员的特定部门/用户组). If it is restricted, other users will not be able to find or chat with the bot.
