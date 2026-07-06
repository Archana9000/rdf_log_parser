RDF Log Parser - Setup & Usage Guide
=====================================

Prerequisites:
- Python 3.6+ installed
- Access to \\Aalfsppdc001\bpg$\FES File Transfers\Evolution\DataFiles\PROD\

Step 1: Create folder structure
-------------------------------
mkdir C:\Users\%USERNAME%\renewelautomation
mkdir C:\Users\%USERNAME%\renewelautomation\input
mkdir C:\Users\%USERNAME%\renewelautomation\output

Step 2: Copy these files
------------------------
- rdf_log_parser\rdf_log_parser.py          -> the main tool
- rdf_log_parser\error_knowledge_base.json   -> error patterns & actions

Step 3 (required for Confluence posting):
-----------------------------------------
1. Go to: https://cmp.allianz.net/plugins/personalaccesstokens/usertokens.action
2. Create a new token
3. Create file C:\Users\%USERNAME%\.config\mcp\env.wsl with:

   CONFLUENCE_URL=https://cmp.allianz.net
   CONFLUENCE_PERSONAL_TOKEN=<paste-your-token-here>
   CONFLUENCE_SSL_VERIFY=false

===================================================================
USAGE - 4 Ways to Run
===================================================================

Option 1: Interactive Agent Mode (recommended)
----------------------------------------------
cd C:\Users\%USERNAME%\renewelautomation
python rdf_log_parser\rdf_log_parser.py --agent

  - Prompts you for a date (e.g. 20260610) or 'all' for batch
  - Parses logs, classifies errors, shows result
  - Asks for your approval before posting to Confluence
  - No commands to remember!

Option 2: Single Day (command line)
-----------------------------------
cd C:\Users\%USERNAME%\renewelautomation

REM Copy today's logs (replace 20260610 with today's date)
xcopy "\\Aalfsppdc001\bpg$\FES File Transfers\Evolution\DataFiles\PROD\input\20260610" "input\20260610\" /E /Y
xcopy "\\Aalfsppdc001\bpg$\FES File Transfers\Evolution\DataFiles\PROD\output\20260610" "output\20260610\" /E /Y

REM Parse & review
python rdf_log_parser\rdf_log_parser.py output\20260610

REM If OK, post to Confluence
python rdf_log_parser\rdf_log_parser.py output\20260610 --post

Option 3: Batch (all dates at once)
------------------------------------
python rdf_log_parser\rdf_log_parser.py output --post

This parses every date folder inside output\ and posts one combined result.

Option 4: AI Agent via Kiro Chat
---------------------------------
Open Kiro chat and type: "Parse today's RDF logs"
Agent runs the parser, shows result, posts on your approval.

===================================================================
KNOWLEDGE BASE
===================================================================

The tool classifies errors by matching the ERROR MESSAGE PATTERN
(not the policy number, since that changes every time).

8 known patterns are defined in error_knowledge_base.json:
- INVALID_AGENT          -> Email to Antonietta
- POLICY_IN_FORCE        -> No action needed
- INVALID_SUNRISE_FOLDER_RANGE -> Send as Import
- CONTRACT_NOT_FOUND     -> Send as Import
- INVITE_RENEWAL_NOT_CLOSED    -> Send as Import
- INVITE_RENEWAL_CANCELLED     -> Check POLISY
- INVALID_BIND_STATE     -> Check POLISY if renewed
- DATABASE_ERROR         -> Retry / raise to I&O

To add a new pattern, edit error_knowledge_base.json:
{
  "MY_NEW_ERROR": {
    "pattern": "some keyword|another keyword",
    "action": "What to do",
    "notes": "Description",
    "occurrences": 0,
    "last_seen": ""
  }
}

Refresh knowledge base from Confluence (monthly):
python rdf_log_parser\rdf_log_parser.py --rebuild-kb

===================================================================
OUTPUT
===================================================================

Results saved to: output\rdf_result_<date>.txt

The output contains:
- Records processed (input vs job1 vs job2 count verification)
- Error details with classification (known vs new)
- Suggested action for each error
- Confluence table ready to copy-paste

When --post is used, a formatted table is posted as a comment
on the Confluence "Batch Renewal Failures: 2026" page.

===================================================================
AI-POWERED ROOT CAUSE ANALYSIS (for unknown errors)
===================================================================

When the parser encounters an error that does NOT match any known pattern
in error_knowledge_base.json, it automatically invokes Kiro CLI to:

1. Extract the Java class and line number from the stack trace
2. Fetch the actual source code from the aztau-java/nevo GitHub repo
3. Send the error + code context to the AI for analysis
4. Return a classification, root cause description, and recommended action

Prerequisites for AI investigation:
------------------------------------
- kiro-cli installed and on PATH (WSL: /home/<user>/.local/bin/kiro-cli)
- GitHub Enterprise token in ~/.config/mcp/env.wsl:

   GITHUB_PERSONAL_ACCESS_TOKEN=<your-github-enterprise-token>
   GITHUB_HOST=https://github.developer.allianz.io

How it works:
-------------
  Error detected → Not in knowledge base?
    → llm_investigate() called
      → Extracts stack trace (class, file, line number)
      → fetch_source_from_repo() fetches Java source from aztau-java/nevo
      → Sends error + code snippet to Kiro CLI (--no-interactive)
      → Kiro analyzes and returns: CATEGORY|description|action
    → Result displayed to user with AI-suggested resolution

Example (demo folder: output\20260623):
----------------------------------------
- Error 1: INVALID_AGENT → matched instantly from knowledge base
- Error 2: STALE_REFERENCE workflow error → UNKNOWN, triggers AI analysis
  → AI reads ProcessDownloadFile.java from nevo repo
  → Identifies concurrent modification / optimistic lock conflict
  → Suggests: "Retry the renewal, check if policy locked by another process"

Running from WSL (recommended for AI features):
-------------------------------------------------
cd /mnt/c/Users/gaok/renewelautomation
python3 rdf_log_parser/rdf_log_parser.py --agent

Note: AI investigation requires kiro-cli which runs in WSL.
If running from Windows CMD, ensure WSL is available (uses 'wsl kiro-cli').
