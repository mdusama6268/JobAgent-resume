# JOBAGENT - End-to-End Autonomous ATS Job Application Agent

**JOBAGENT** is a local, privacy-first Python automation agent powered by **Playwright** and a local **Ollama** LLM (e.g. Llama 3.2). 

It is specifically engineered to handle modern **Applicant Tracking Systems (ATS)** such as **Greenhouse**, **Lever**, and custom enterprise career portals:
1. **Resume File Uploads**: Automatically detects file input elements and upload triggers (`input[type='file']`, "Attach Resume", "Upload CV") and attaches your local resume PDF using Playwright's `set_input_files()`.
2. **ATS Compliance Dropdowns**: Intelligently maps standard and custom ATS dropdowns (Visa Sponsorship, Work Authorization, Relocation/Hybrid Preferences, AI Evaluation Policies, Referral Sources).
3. **Smart Long-Form Answering (200–400 words)**: Analyzes custom application questions (e.g., *"Why Anthropic?"*, *"Why are you interested in this role?"*, *"Describe a major scaling initiative"*) and prompts local Ollama (Llama 3.2) to synthesize tailored, executive responses highlighting your 8+ years scaling operations at Zomato and building GharJodo.
4. **Persistent Browser Context**: Retains login sessions and cookies across LinkedIn, Naukri, or job portals in a local `browser_profile/` directory to prevent bot-detection barriers.
5. **Autonomous Form Submission**: Identifies the primary application submission button, triggers submission autonomously, and confirms the submission indicator.

---

## 👤 Candidate Profile Highlights (`profile.json`)

- **Name**: Mohd Huzefa
- **Email**: `mdhzfa@gmail.com` | **Phone**: `+91 6268643512`
- **Location**: Bhopal, Madhya Pradesh, India
- **Resume Path**: `G:\JobAgent\Mohd_Huzefa_Resume.pdf`
- **Education**: Bachelor of Technology (B.Tech) in **Mechanical Engineering**, 2018 (Technocrats Institute of Technology, Bhopal)
- **GitHub**: [github.com/mdusama688](https://github.com/mdusama688)
- **LinkedIn**: [linkedin.com/in/mdhzfa](https://linkedin.com/in/mdhzfa)
- **Live Project / Portfolio**: [GharJodo - Broker Ki Smart Digital Diary](https://gharjodo.vercel.app/)
- **Core Experience**: 8+ years total. Current Operations & Tech Execution Lead / Assistant Program Manager at Zomato Ltd. (since 2018, scaling *Food on Trains* across 200+ railway stations with IRCTC, P&L management, automation). Founder and creator of GharJodo (deployed for pilot testing in 2026).
- **Target Roles**: AI Workflow Specialist, Operations Lead, Product Manager, Program Manager
- **Target Regions**: Europe, GCC, India

---

## 📂 Project Structure

```text
JobAgent/
├── profile.json            # Structured candidate profile (Zomato, GharJodo, resume_path, ATS preferences)
├── Mohd_Huzefa_Resume.pdf  # Candidate resume PDF for automated ATS file uploads
├── config.py               # Centralized configuration (Ollama, headless, auto-submit, paths)
├── session_manager.py      # Persistent browser context manager (cookies saved in browser_profile/)
├── searcher.py             # Asynchronous job discovery script for target roles
├── agent.py                # Core ATS engine: resume uploads, dropdown mapping, smart textareas & submission
├── main.py                 # Unified CLI (apply, search, login, sample)
├── sample_form.html        # Greenhouse/Lever styled mock application form with file upload & dropdowns
├── browser_profile/        # Persistent browser session storage (preserves login state)
└── README.md               # Complete documentation
```

---

## ⚙️ Prerequisites & Setup

### 1. Install Python Dependencies

```bash
pip install playwright ollama
```

### 2. Install Playwright Browsers

```bash
playwright install chromium
```

### 3. Setup Ollama (Local AI)

Ensure Ollama is running (`http://localhost:11434`) and pull `llama3.2`:

```bash
ollama pull llama3.2
```

*(Note: If you have `llama3` installed, JOBAGENT automatically detects and uses it as an active fallback).*

---

## 🚀 Usage Guide

### 1. Test ATS Automation (Resume Upload + Dropdowns + AI Long-Form Answers)

Run the local Greenhouse/Lever ATS simulation form:

```bash
# Visible browser window with auto-submission
python main.py apply --sample --auto-submit

# Headless background execution
python main.py apply --sample --auto-submit --headless --no-pause
```

### 2. Apply to Live ATS URLs (Greenhouse / Lever / Custom)

```bash
# Auto-fill fields, upload resume, and pause for your final review before submitting
python main.py apply --url "https://boards.greenhouse.io/company/jobs/12345"

# Fully autonomous: auto-fill, upload resume, and automatically click Submit
python main.py apply --url "https://jobs.lever.co/company/abcdef-1234" --auto-submit
```

### 3. Log In Once to Portals (Save Persistent Sessions)

To eliminate login barriers on LinkedIn, Naukri, or job boards:

```bash
python main.py login --portal "LinkedIn" --url "https://www.linkedin.com/login"
```

A visible browser opens. Complete login manually; cookies and tokens are permanently saved in `./browser_profile/`.

### 4. Search for Jobs

```bash
# Search for specific role
python main.py search --query "AI Workflow Specialist" --location "Remote" --limit 5

# Batch search all profile target roles (saves to discovered_jobs.json)
python main.py search --batch --location "Remote"
```

---

## 🛠️ ATS Feature Highlights

- **Resume Upload**: Automatically maps your resume PDF from `profile.json` (`Mohd_Huzefa_Resume.pdf`) and attaches it to `input[type="file"]`.
- **ATS Dropdowns**:
  - Visa Sponsorship -> `No`
  - Work Authorization -> `Yes`
  - Relocation / Hybrid -> `Yes`
  - AI Evaluation Policy Agreement -> `Yes`
  - Referral Source -> `LinkedIn`
  - Total Experience -> `8+`
- **Smart Textarea Answering**:
  - Automatically drafts a compelling 200–400 word statement for questions like *"Why Anthropic?"*, *"Why are you interested in this role?"*, or *"Describe an operational initiative you scaled"*.
  - Weaves in Huzefa's real metrics: scaling Zomato's Food on Trains across 200+ railway stations, building GharJodo (pilot testing in 2026), Mechanical Engineering (2018), and Python/Playwright automation.
  - Features an instant 250-word executive fallback if the local LLM response exceeds 35s.
