# Unified Builder VOC Report

Weekly automated Voice of Customer analysis for the Mailchimp unified builder and email builder experience.

## What this does

- Pulls HVC customer feedback ($299+ MRR) from two Slack channels: `#hvc_feedback` and `#mc-hvc-escalations`
- Classifies feedback by theme, sentiment, severity, and builder surface
- Deduplicates by user_id + theme per month
- Generates a self-contained HTML report with charts and priority matrices
- Publishes to GitHub Pages every Monday

## Access the report

**GitHub Pages URL:** https://deepakp1308.github.io/unified-builder-voc-report/

## How it works

1. GitHub Actions cron triggers every Monday at 9am PT
2. `scripts/generate_report.py` pulls new Slack messages since last run
3. Appends to `data/analysis.json` cumulative dataset
4. Regenerates `index.html` with updated charts and tables
5. Commits and pushes — GitHub Pages auto-deploys

## Setup

### Prerequisites

- Python 3.11+
- Slack Bot Token with access to `#hvc_feedback` and `#mc-hvc-escalations`

### Secrets

Add the following repo secret in GitHub Settings > Secrets > Actions:

- `SLACK_BOT_TOKEN` — Slack bot token (xoxb-...)

### Manual run

```bash
pip install -r scripts/requirements.txt
export SLACK_BOT_TOKEN=xoxb-your-token
python scripts/generate_report.py
```

## Schedule

Runs every Monday for 10 weeks (May 19 – July 21, 2026). After that, the workflow remains but can be disabled.

## Data sources

| Channel | Type | Content |
|---------|------|---------|
| #hvc_feedback (C051Y4H98VB) | Automated surveys | PRS, CSAT, In-App Feedback Badge responses from $299+ MRR customers |
| #mc-hvc-escalations (C095FJ3SQF4) | CS escalations | Product feedback for $5K+ MRR accounts filed by Customer Success |
