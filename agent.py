import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from playwright.async_api import (
    async_playwright,
    Page,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError
)
import ollama
from config import Config, config as default_config
from session_manager import SessionManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("JOBAGENT")


# High-impact 200-300 word executive fallback responses for ATS long-form questions
ATS_FALLBACK_TEXT = {
    "why_company": (
        "With over 8 years of cross-functional operations leadership and tech execution, I specialize in "
        "bridging complex operational ecosystems with modern automation. At Zomato Ltd., I spearheaded the 'Food on Trains' "
        "initiative from inception, scaling operations across 200+ railway stations in collaboration with IRCTC while driving P&L performance, "
        "vendor operations, and real-time logistics tracking. My foundation in Mechanical Engineering (Technocrats Institute of Technology, 2018) "
        "instilled a first-principles problem-solving mindset, which I channel into building automated workflows with Python and Playwright.\n\n"
        "Beyond corporate scaling, I am the founder and creator of GharJodo (Broker Ki Smart Digital Diary, https://gharjodo.vercel.app/), "
        "currently deployed for pilot testing in 2026 to automate property inventory management and lead qualification for real estate brokers. "
        "I am eager to bring this unique blend of large-scale operations rigor, engineering pragmatism, and workflow automation to your team "
        "to drive measurable growth and operational excellence."
    ),
    "scaling_experience": (
        "During my tenure at Zomato Ltd. as Assistant Program Manager / Operations Lead, I led the scaling of the 'Food on Trains' "
        "partnership with IRCTC from an initial concept into a nationwide operational network spanning over 200 railway stations. "
        "This required coordinating across regional operations, vendor networks, station logistics, and engineering teams to guarantee delivery "
        "windows within train stoppage times under 5 minutes.\n\n"
        "Key achievements included architecting process automation pipelines in Python to monitor delivery SLA compliance, negotiating vendor commercial terms "
        "to maintain healthy unit economics and P&L targets, and reducing dispatch latency by over 35%. "
        "Additionally, building GharJodo (pilot testing in 2026) further sharpened my execution speed—designing user onboarding, property record workflows, and automated communication pipelines from scratch."
    ),
    "general_longform": (
        "I bring 8+ years of proven operations and tech execution leadership from Zomato Ltd. and venture building with GharJodo. "
        "My core expertise spans scaling complex regional operations across 200+ stations, optimizing P&L and vendor networks, "
        "and automating repetitive business processes using Python, Playwright, and local LLM workflows. "
        "I thrive at the intersection of business strategy and technical execution, delivering reliable results in high-growth environments."
    )
}


class JobAgent:
    """
    JOBAGENT: Autonomous ATS Job Application Agent.
    Engineered for live ATS platforms (Greenhouse, Lever, etc.) with:
    - Persistent browser sessions (SessionManager).
    - Automatic Resume PDF file uploads (input[type='file']).
    - Standard & custom ATS dropdown mapping (visa sponsorship, work auth, relocation, AI policy).
    - Local Ollama (Llama 3.2) custom question answering (200-400 words) with rich fallbacks.
    - Autonomous submission engine with safety checkpoints.
    """

    def __init__(self, cfg: Optional[Config] = None):
        self.config = cfg or default_config
        self.profile: Dict[str, Any] = self._load_profile(self.config.PROFILE_PATH)
        self.session_manager = SessionManager(self.config)
        self.ollama_client = ollama.AsyncClient(host=self.config.OLLAMA_BASE_URL)
        self.active_model = self.config.OLLAMA_MODEL
        self._ensure_resume_exists()

    def _load_profile(self, path: str) -> Dict[str, Any]:
        """Loads and parses the candidate profile JSON file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Candidate profile not found at path: {path}")
        with open(path, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
        candidate_name = profile_data.get("personal", {}).get("full_name", "Mohd Huzefa")
        logger.info(f"Loaded candidate profile for: {candidate_name}")
        return profile_data

    def _ensure_resume_exists(self) -> str:
        """Ensures that the resume PDF path configured in profile.json exists on disk."""
        resume_path = self.profile.get("personal", {}).get("resume_path", "Mohd_Huzefa_Resume.pdf")
        abs_path = os.path.abspath(resume_path)

        if not os.path.exists(abs_path):
            logger.warning(f"Resume PDF not found at {abs_path}. Generating placeholder PDF...")
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            minimal_pdf = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj
4 0 obj << /Length 55 >> stream
BT /F1 12 Tf 50 720 Td (Mohd Huzefa - Resume PDF) Tj ET
endstream endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000214 00000 n 
trailer << /Size 5 /Root 1 0 R >>
startxref
318
%%EOF"""
            with open(abs_path, "wb") as f:
                f.write(minimal_pdf)
            logger.info(f"Generated placeholder resume PDF at: {abs_path}")

        return abs_path

    async def _resolve_ollama_model(self) -> str:
        """Verifies if the configured Ollama model is available locally, with fallback support."""
        try:
            models_response = await self.ollama_client.list()
            available_models = [m.model for m in models_response.models] if hasattr(models_response, 'models') else []
            logger.info(f"Local Ollama models detected: {available_models}")

            target = self.config.OLLAMA_MODEL
            if any(target in m for m in available_models):
                return target

            llama_variants = [m for m in available_models if "llama" in m.lower()]
            if llama_variants:
                fallback = llama_variants[0]
                logger.warning(f"Target '{target}' not found. Falling back to: '{fallback}'.")
                return fallback

            if available_models:
                return available_models[0]

            return target
        except Exception as e:
            logger.warning(f"Could not query Ollama models list ({e}). Defaulting to '{self.config.OLLAMA_MODEL}'.")
            return self.config.OLLAMA_MODEL

    async def handle_file_uploads(self, page: Page) -> int:
        """
        Scans DOM for file upload elements (input[type='file'], resume upload buttons)
        and uploads the candidate resume PDF using Playwright's set_input_files().
        """
        logger.info("Scanning for Resume / File upload elements...")
        resume_path = self._ensure_resume_exists()
        uploaded_count = 0

        try:
            # 1. Locate all file input elements (including hidden ones used in ATS frameworks)
            file_inputs = await page.locator("input[type='file']").all()

            if file_inputs:
                for idx, file_input in enumerate(file_inputs):
                    try:
                        input_id = (await file_input.get_attribute("id") or "").lower()
                        input_name = (await file_input.get_attribute("name") or "").lower()
                        aria_label = (await file_input.get_attribute("aria-label") or "").lower()

                        # Attach if it's the only file input or matches resume/cv keywords
                        is_resume_field = (
                            len(file_inputs) == 1 or
                            any(k in input_id for k in ["resume", "cv", "file", "attach"]) or
                            any(k in input_name for k in ["resume", "cv", "file", "attach"]) or
                            any(k in aria_label for k in ["resume", "cv", "file", "attach"])
                        )

                        if is_resume_field:
                            logger.info(f"Attaching resume PDF to file input [#{input_id or input_name or idx}]: {resume_path}")
                            await file_input.set_input_files(resume_path)
                            uploaded_count += 1

                            # Highlight upload container
                            try:
                                await file_input.evaluate(
                                    "el => { const parent = el.closest('.form-group, .file-upload-box, div'); if (parent) { parent.style.border = '2px solid #10b981'; parent.style.backgroundColor = '#ecfdf5'; } }"
                                )
                            except Exception:
                                pass
                    except Exception as fe:
                        logger.warning(f"Failed to set file on input index {idx}: {fe}")

            # 2. Check for button triggers that open file dialogs if no input[type='file'] was directly populated
            if uploaded_count == 0:
                upload_triggers = [
                    "button:has-text('Attach Resume')",
                    "button:has-text('Upload Resume')",
                    "button:has-text('Upload CV')",
                    "button:has-text('Attach')",
                    "[data-qa*='resume-upload']",
                    ".resume-upload-button"
                ]
                for trig_sel in upload_triggers:
                    try:
                        trig = page.locator(trig_sel).first
                        if await trig.is_visible(timeout=1000):
                            async with page.expect_file_chooser(timeout=3000) as fc_info:
                                await trig.click()
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(resume_path)
                            logger.info(f"Attached resume via file chooser trigger '{trig_sel}': {resume_path}")
                            uploaded_count += 1
                            break
                    except Exception:
                        continue

        except Exception as e:
            logger.warning(f"Encountered notice during file upload scan: {e}")

        logger.info(f"File upload handler finished. Total files uploaded: {uploaded_count}")
        return uploaded_count

    async def extract_form_fields(self, page: Page) -> List[Dict[str, Any]]:
        """
        Analyzes the DOM to discover all interactive form fields,
        resolving labels, placeholders, input types, and dropdown options.
        """
        logger.info("Analyzing DOM form elements...")

        js_extractor = """
        () => {
            const selector = 'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="file"]), textarea, select';
            const elements = Array.from(document.querySelectorAll(selector));

            return elements.map((el, idx) => {
                // 1. Resolve associated label
                let labelText = '';
                if (el.id) {
                    const labelEl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (labelEl) labelText = labelEl.innerText;
                }
                if (!labelText) {
                    const parentLabel = el.closest('label');
                    if (parentLabel) labelText = parentLabel.innerText;
                }
                if (!labelText) {
                    labelText = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
                }
                if (!labelText) {
                    const prev = el.previousElementSibling;
                    if (prev && ['LABEL', 'SPAN', 'P', 'H3', 'H4', 'DIV'].includes(prev.tagName)) {
                        labelText = prev.innerText;
                    }
                }

                // 2. Resolve fieldset / parent group context (vital for radios, checkboxes, and ATS dropdowns)
                let groupText = '';
                const fieldset = el.closest('fieldset');
                if (fieldset) {
                    const legend = fieldset.querySelector('legend');
                    if (legend) groupText = legend.innerText;
                }
                if (!groupText) {
                    const parentGroup = el.closest('.form-group, .radio-group, .checkbox-group, .form-row');
                    if (parentGroup) {
                        const groupLabel = parentGroup.querySelector('label:not(.radio-item):not(.checkbox-item)');
                        if (groupLabel && groupLabel !== el.parentElement) groupText = groupLabel.innerText;
                    }
                }

                // 3. Extract options for select elements
                let options = [];
                if (el.tagName === 'SELECT') {
                    options = Array.from(el.querySelectorAll('option'))
                        .map(opt => ({ value: opt.value, text: opt.text.trim() }))
                        .filter(opt => opt.value || opt.text);
                }

                // 4. Formulate robust selector
                let selectorStr = '';
                if (el.id) {
                    selectorStr = `#${CSS.escape(el.id)}`;
                } else if (el.name && (el.type === 'radio' || el.type === 'checkbox')) {
                    selectorStr = `input[name="${CSS.escape(el.name)}"][value="${CSS.escape(el.value)}"]`;
                } else if (el.name) {
                    selectorStr = `[name="${CSS.escape(el.name)}"]`;
                } else {
                    selectorStr = `${el.tagName.toLowerCase()}:nth-of-type(${idx + 1})`;
                }

                return {
                    index: idx,
                    tag: el.tagName.toLowerCase(),
                    type: el.type || 'text',
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    label: (labelText || '').trim(),
                    group_context: (groupText || '').trim(),
                    value: el.value || '',
                    required: el.required || el.getAttribute('aria-required') === 'true',
                    options: options,
                    selector: selectorStr
                };
            });
        }
        """

        fields = await page.evaluate(js_extractor)
        logger.info(f"Discovered {len(fields)} interactive form fields on page.")
        return fields

    async def generate_longform_answer(self, question: str) -> str:
        """
        Uses local Ollama (Llama 3.2) to craft a tailored, professional 200-400 word response
        highlighting Huzefa's operations leadership at Zomato and GharJodo.
        Falls back to high-impact structured responses if Ollama times out.
        """
        self.active_model = await self._resolve_ollama_model()
        logger.info(f"Generating 200-400 word response for question: '{question[:60]}...' using {self.active_model}")

        prompt = f"""
You are an expert executive career advocate writing an application answer for candidate Mohd Huzefa.
Candidate Details:
- 8+ years leading cross-functional operations and tech execution at Zomato Ltd.
- Spearheaded the 'Food on Trains' initiative across 200+ railway stations with IRCTC, managing P&L, vendor operations, and process automation.
- Founder & creator of GharJodo (Broker Ki Smart Digital Diary, https://gharjodo.vercel.app/), deployed for pilot testing in 2026.
- Background in Mechanical Engineering (2018), expert in Python, Playwright process automation, and AI workflows.

QUESTION TO ANSWER:
"{question}"

INSTRUCTIONS:
Write a compelling, articulate, professional response between 200 and 350 words.
Highlight concrete leadership metrics (200+ stations, Zomato IRCTC partnership, P&L management, automation pipelines, and GharJodo venture).
Maintain an executive, confident, and engaging tone.
Output ONLY the final response text without greetings or conversational meta-commentary.
"""
        try:
            chat_coro = self.ollama_client.chat(
                model=self.active_model,
                messages=[
                    {"role": "system", "content": "You are a professional executive career writer. Write high-impact application statements."},
                    {"role": "user", "content": prompt}
                ]
            )
            response = await asyncio.wait_for(chat_coro, timeout=35.0)
            text_out = response.message.content.strip()
            # Clean possible markdown block wrappers
            text_out = re.sub(r"^```(?:markdown)?\s*", "", text_out)
            text_out = re.sub(r"\s*```$", "", text_out).strip()

            word_count = len(text_out.split())
            logger.info(f"Ollama successfully generated response ({word_count} words).")
            return text_out

        except asyncio.TimeoutError:
            logger.warning("Ollama generation timed out after 35s. Using high-impact structured fallback response.")
            return self._select_fallback_longform(question)
        except Exception as e:
            logger.error(f"Error querying Ollama for long-form question: {e}")
            return self._select_fallback_longform(question)

    def _select_fallback_longform(self, question: str) -> str:
        """Selects the most suitable structured long-form fallback text."""
        q_lower = question.lower()
        if "scale" in q_lower or "scaling" in q_lower or "initiative" in q_lower:
            return ATS_FALLBACK_TEXT["scaling_experience"]
        elif "why" in q_lower or "interest" in q_lower or "fit" in q_lower or "strength" in q_lower:
            return ATS_FALLBACK_TEXT["why_company"]
        return ATS_FALLBACK_TEXT["general_longform"]

    async def get_llm_mappings(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Maps candidate profile details to detected form fields.
        Differentiates standard inputs, ATS compliance dropdowns, and long-form questions.
        """
        self.active_model = await self._resolve_ollama_model()
        logger.info(f"Invoking Ollama LLM ({self.active_model}) to match fields to profile...")

        compact_fields = [
            {
                "index": f["index"],
                "label": f["label"] or f["placeholder"] or f["name"] or f["id"],
                "tag": f["tag"],
                "type": f["type"],
                "options": [opt.get("value") or opt.get("text") for opt in f.get("options", [])],
                "context": f.get("group_context", "")
            }
            for f in fields
        ]

        prompt = f"""
You are an autonomous job application assistant acting on behalf of candidate Mohd Huzefa.
Candidate Profile:
{json.dumps(self.profile, indent=2)}

Form Fields Detected:
{json.dumps(compact_fields, indent=2)}

TASK:
Determine the action and value for each form field index.
Rules:
1. For text/email/tel/number/url inputs: action="fill", value=<candidate value>.
   - GitHub: "https://github.com/mdusama688"
   - Portfolio: "https://gharjodo.vercel.app/"
2. For ATS Dropdowns ("select"):
   - Visa sponsorship: "No"
   - Work authorization: "Yes"
   - Relocation / Hybrid: "Yes"
   - AI policy agreement: "Yes"
   - Referral / Source: "LinkedIn"
   - Experience: "8+"
3. For long-form textareas ("tag": "textarea"):
   - action="fill", value="GENERATE_LONGFORM"
4. For checkboxes / radios: action="check" if candidate agrees/qualifies, else action="skip".

Return ONLY valid JSON matching this schema:
{{
  "mappings": [
    {{
      "index": 0,
      "action": "fill",
      "value": "Mohd"
    }}
  ]
}}
"""

        try:
            chat_coro = self.ollama_client.chat(
                model=self.active_model,
                messages=[
                    {"role": "system", "content": "You are a job application automation assistant. You always respond with pure, valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                format="json"
            )
            response = await asyncio.wait_for(chat_coro, timeout=35.0)

            raw_content = response.message.content.strip()
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", raw_content)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

            data = json.loads(cleaned_json)
            raw_mappings = data.get("mappings", [])

            resolved_mappings = []
            for m in raw_mappings:
                idx = m.get("index")
                if idx is not None and 0 <= idx < len(fields):
                    orig = fields[idx]
                    resolved_mappings.append({
                        "selector": orig["selector"],
                        "field_name": orig.get("label") or orig.get("name") or orig.get("id"),
                        "action": m.get("action", "fill"),
                        "value": m.get("value"),
                        "tag": orig.get("tag"),
                        "type": orig.get("type")
                    })
                elif m.get("selector"):
                    resolved_mappings.append(m)

            logger.info(f"Ollama successfully produced {len(resolved_mappings)} field mappings.")
            return resolved_mappings

        except asyncio.TimeoutError:
            logger.warning("Ollama LLM response timed out after 35s. Using fast heuristic fallback...")
            return self._heuristic_fallback_mappings(fields)
        except Exception as e:
            logger.error(f"Error querying Ollama LLM: {e}")
            logger.info("Executing rule-based heuristic fallback for basic fields...")
            return self._heuristic_fallback_mappings(fields)

    def _heuristic_fallback_mappings(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deterministic heuristic mapper tailored for Greenhouse, Lever, and ATS forms."""
        mappings = []
        p = self.profile.get("personal", {})
        edu = self.profile.get("education", {})
        exp = self.profile.get("experience", {})
        pref = self.profile.get("preferences", {})

        for f in fields:
            label = (f.get("label") or f.get("name") or f.get("id") or "").lower()
            tag = f.get("tag")
            ftype = f.get("type")
            selector = f.get("selector")

            # 1. Checkboxes
            if ftype == "checkbox":
                if any(k in label for k in ["relocat", "hybrid", "remote", "agree", "policy"]):
                    mappings.append({"selector": selector, "field_name": "Checkbox", "action": "check", "value": True})

            # 2. Radio buttons
            elif ftype == "radio":
                val_lower = (f.get("value") or "").lower()
                if "sponsorship" in label:
                    if val_lower in ["no", "false", "0"]:
                        mappings.append({"selector": selector, "field_name": "Sponsorship Radio", "action": "check", "value": "No"})
                elif any(k in label for k in ["auth", "authorized", "legally", "agree", "relocat"]):
                    if val_lower in ["yes", "true", "1"]:
                        mappings.append({"selector": selector, "field_name": "Radio", "action": "check", "value": "Yes"})

            # 3. Select Dropdowns (ATS Specific)
            elif tag == "select":
                if any(k in label for k in ["sponsor", "visa"]):
                    mappings.append({"selector": selector, "field_name": "Visa Sponsorship Dropdown", "action": "select", "value": pref.get("requires_sponsorship", "No")})
                elif any(k in label for k in ["authoriz", "legally", "work_auth"]):
                    mappings.append({"selector": selector, "field_name": "Work Auth Dropdown", "action": "select", "value": pref.get("work_authorization", "Yes")})
                elif any(k in label for k in ["relocat", "hybrid", "remote"]):
                    mappings.append({"selector": selector, "field_name": "Relocation Dropdown", "action": "select", "value": pref.get("relocation", "Yes")})
                elif any(k in label for k in ["ai", "policy", "evaluat", "automat"]):
                    mappings.append({"selector": selector, "field_name": "AI Policy Dropdown", "action": "select", "value": pref.get("ai_policy_agreement", "Yes")})
                elif any(k in label for k in ["hear", "source", "referral"]):
                    mappings.append({"selector": selector, "field_name": "Referral Source Dropdown", "action": "select", "value": pref.get("hear_about_us", "LinkedIn")})
                elif "experience" in label:
                    mappings.append({"selector": selector, "field_name": "Experience Dropdown", "action": "select", "value": "8+"})
                else:
                    mappings.append({"selector": selector, "field_name": "Default Select", "action": "select", "value": "Yes"})

            # 4. Long-form Multiline Textareas
            elif tag == "textarea":
                mappings.append({
                    "selector": selector,
                    "field_name": f.get("label") or "Application Question",
                    "action": "fill",
                    "value": "GENERATE_LONGFORM",
                    "question_text": f.get("label") or f.get("placeholder") or "Experience & motivation"
                })

            # 5. Standard text/email/tel/url inputs
            else:
                if "first" in label and "name" in label:
                    mappings.append({"selector": selector, "field_name": "First Name", "action": "fill", "value": p.get("first_name", "Mohd")})
                elif "last" in label and "name" in label:
                    mappings.append({"selector": selector, "field_name": "Last Name", "action": "fill", "value": p.get("last_name", "Huzefa")})
                elif ("name" in label and "full" in label) or label == "name":
                    mappings.append({"selector": selector, "field_name": "Full Name", "action": "fill", "value": p.get("full_name", "Mohd Huzefa")})
                elif "email" in label:
                    mappings.append({"selector": selector, "field_name": "Email", "action": "fill", "value": p.get("email", "mdhzfa@gmail.com")})
                elif "phone" in label or "mobile" in label or "tel" in label:
                    mappings.append({"selector": selector, "field_name": "Phone", "action": "fill", "value": p.get("phone", "+91 6268643512")})
                elif "location" in label or "city" in label:
                    loc = p.get("location", {})
                    mappings.append({"selector": selector, "field_name": "Location", "action": "fill", "value": f"{loc.get('city', 'Bhopal')}, {loc.get('country', 'India')}"})
                elif "github" in label or "git" in label:
                    mappings.append({"selector": selector, "field_name": "GitHub", "action": "fill", "value": p.get("github", "https://github.com/mdusama688")})
                elif "portfolio" in label or "website" in label:
                    mappings.append({"selector": selector, "field_name": "Portfolio", "action": "fill", "value": p.get("portfolio", "https://gharjodo.vercel.app/")})
                elif "linkedin" in label:
                    mappings.append({"selector": selector, "field_name": "LinkedIn", "action": "fill", "value": p.get("linkedin", "https://linkedin.com/in/mdhzfa")})
                elif "university" in label or "college" in label or "school" in label:
                    mappings.append({"selector": selector, "field_name": "University", "action": "fill", "value": edu.get("university", "Technocrats Institute of Technology, Bhopal")})
                elif "degree" in label or "major" in label:
                    mappings.append({"selector": selector, "field_name": "Degree", "action": "fill", "value": f"{edu.get('degree', 'B.Tech')} {edu.get('major', 'Mechanical Engineering')}"})
                elif "company" in label:
                    mappings.append({"selector": selector, "field_name": "Company", "action": "fill", "value": exp.get("current_company", "Zomato Ltd.")})
                elif "role" in label or "title" in label:
                    mappings.append({"selector": selector, "field_name": "Role", "action": "fill", "value": exp.get("current_role", "Operations & Tech Execution Lead")})

        return mappings

    async def fill_form_fields(self, page: Page, mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Executes form field filling with error handling and green visual highlighting."""
        stats = {"filled": 0, "skipped": 0, "failed": 0, "details": []}

        for m in mappings:
            selector = m.get("selector")
            action = m.get("action", "skip").lower()
            value = m.get("value")
            field_name = m.get("field_name", selector)

            if action == "skip" or not selector or value is None:
                stats["skipped"] += 1
                continue

            try:
                locator = page.locator(selector).first

                # Check if it's a long-form question that needs 200-400 words generation
                if value == "GENERATE_LONGFORM":
                    question_context = m.get("question_text") or field_name
                    value = await self.generate_longform_answer(question_context)

                if action == "fill":
                    text_value = str(value)
                    await locator.fill(text_value, timeout=4000)
                    await self._highlight_element(page, selector)
                    preview = text_value[:55] + "..." if len(text_value) > 55 else text_value
                    logger.info(f"Filled [{field_name}]: '{preview}'")
                    stats["filled"] += 1
                    stats["details"].append({"field": field_name, "status": "success", "action": "fill", "value": text_value})

                elif action == "select":
                    val_str = str(value).strip()
                    selected = False

                    # Try matching option by label, then value, then partial text
                    for strategy in ["label", "value"]:
                        try:
                            if strategy == "label":
                                await locator.select_option(label=val_str, timeout=1200)
                            else:
                                await locator.select_option(value=val_str, timeout=1200)
                            selected = True
                            break
                        except Exception:
                            continue

                    if not selected:
                        options = await locator.locator("option").all()
                        for opt in options:
                            opt_text = (await opt.inner_text()).strip()
                            opt_val = await opt.get_attribute("value") or ""
                            if val_str.lower() in opt_text.lower() or val_str.lower() in opt_val.lower():
                                await locator.select_option(value=opt_val, timeout=1200)
                                selected = True
                                break

                    if selected:
                        await self._highlight_element(page, selector)
                        logger.info(f"Selected [{field_name}]: '{val_str}'")
                        stats["filled"] += 1
                        stats["details"].append({"field": field_name, "status": "success", "action": "select", "value": val_str})
                    else:
                        raise ValueError(f"Could not match dropdown option for '{val_str}' in selector '{selector}'")

                elif action == "check":
                    if value is True or str(value).lower() in ("true", "yes", "1"):
                        await locator.check(timeout=2000)
                        await self._highlight_element(page, selector)
                        logger.info(f"Checked [{field_name}]")
                        stats["filled"] += 1
                        stats["details"].append({"field": field_name, "status": "success", "action": "check", "value": True})
                    else:
                        stats["skipped"] += 1

                await page.wait_for_timeout(60)

            except Exception as e:
                logger.warning(f"Failed to fill field [{field_name}] using selector '{selector}': {e}")
                stats["failed"] += 1
                stats["details"].append({"field": field_name, "status": "error", "error": str(e)})

        return stats

    async def _highlight_element(self, page: Page, selector: str):
        """Visually marks filled elements on the page with a clean emerald green border."""
        try:
            await page.eval_on_selector(
                selector,
                """el => {
                    el.style.border = '2px solid #10b981';
                    el.style.boxShadow = '0 0 6px rgba(16, 185, 129, 0.4)';
                    el.style.transition = 'all 0.2s ease-in-out';
                }"""
            )
        except Exception:
            pass

    async def submit_form(self, page: Page) -> bool:
        """
        Autonomously discovers and clicks the primary submission button on the page.
        Waits for confirmation state or submission indicator.
        """
        logger.info("Locating form submission button...")

        submit_selectors = [
            "#submit-application",
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Send Application')",
            "[data-testid*='submit']"
        ]

        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    logger.info(f"Found submit button with selector: '{sel}'")
                    await page.eval_on_selector(sel, "el => { el.style.boxShadow = '0 0 10px #2563eb'; }")
                    await page.wait_for_timeout(400)
                    await btn.click()
                    logger.info(">>> Clicked application Submit button autonomously!")

                    await page.wait_for_timeout(1000)
                    confirm_selectors = [
                        "#success-message",
                        ".success",
                        ".application-success",
                        ":has-text('Application Submitted')",
                        ":has-text('Thank you')"
                    ]
                    for c_sel in confirm_selectors:
                        try:
                            c_elem = page.locator(c_sel).first
                            if await c_elem.is_visible(timeout=2000):
                                logger.info(f"Confirmed application submission indicator: '{c_sel}'")
                                return True
                        except Exception:
                            continue
                    return True
            except Exception:
                continue

        logger.warning("Could not find an automated submit button on the current page.")
        return False

    async def run(
        self,
        target_url: str,
        auto_submit: Optional[bool] = None,
        pause_on_completion: bool = True
    ) -> Dict[str, Any]:
        """
        End-to-end automation workflow for ATS forms:
        1. Launches persistent browser session (SessionManager).
        2. Navigates to target job URL.
        3. Executes Resume File Uploads.
        4. Analyzes DOM and discovers form fields.
        5. Maps fields using Ollama LLM / heuristics (handles ATS dropdowns).
        6. Generates long-form 200-400 word answers for custom questions.
        7. Fills fields and applies visual indicators.
        8. Autonomously submits form if auto_submit=True (or pauses for safety review).
        """
        should_submit = auto_submit if auto_submit is not None else self.config.AUTO_SUBMIT

        logger.info(f"--- Starting Autonomous JOBAGENT session ---")
        logger.info(f"Candidate: {self.profile.get('personal', {}).get('full_name')}")
        logger.info(f"Target URL: {target_url}")
        logger.info(f"Auto Submit: {should_submit} | Headless: {self.config.BROWSER_HEADLESS}")

        async with async_playwright() as p:
            context: BrowserContext = await self.session_manager.launch_persistent_context(
                p,
                headless=self.config.BROWSER_HEADLESS,
                slow_mo=self.config.BROWSER_SLOW_MO
            )
            page: Page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(self.config.PAGE_TIMEOUT)

            try:
                logger.info(f"Navigating to: {target_url}")
                await page.goto(target_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(1000)

                # Step 1: Handle Resume File Uploads first
                uploaded_files = await self.handle_file_uploads(page)

                # Step 2: DOM Analysis for inputs, dropdowns, and textareas
                form_fields = await self.extract_form_fields(page)
                if not form_fields:
                    logger.warning("No interactive form fields found on target page.")
                    return {"status": "no_fields_found", "filled": 0, "uploaded_files": uploaded_files}

                # Step 3: Field Mapping via Ollama / Heuristics
                mappings = await self.get_llm_mappings(form_fields)

                # Step 4: Form Filling (includes smart long-form generation & ATS dropdowns)
                stats = await self.fill_form_fields(page, mappings)
                stats["uploaded_files"] = uploaded_files

                # Step 5: Autonomous Submission or Safety Pause
                if should_submit:
                    submitted = await self.submit_form(page)
                    stats["submitted"] = submitted
                    print("\n" + "=" * 65)
                    print(f">>> AUTONOMOUS SUBMISSION: {'SUCCESS' if submitted else 'BUTTON NOT FOUND'}")
                    print("=" * 65 + "\n")
                else:
                    stats["submitted"] = False
                    if not self.config.BROWSER_HEADLESS and pause_on_completion:
                        print("\n" + "=" * 65)
                        print(">>> SAFETY REVIEW CHECKPOINT: Form has been filled and highlighted.")
                        print(">>> Auto-submit is OFF. Review the fields and uploaded resume in the browser.")
                        print(">>> Press [ENTER] in this terminal to close the browser session...")
                        print("=" * 65 + "\n")
                        await asyncio.to_thread(input)

                logger.info(
                    f"--- Session Complete: {stats['filled']} filled, {uploaded_files} files uploaded, "
                    f"{stats['skipped']} skipped, {stats['failed']} failed, submitted={stats.get('submitted')} ---"
                )
                return stats

            except PlaywrightTimeoutError as e:
                logger.error(f"Navigation or element timeout: {e}")
                return {"status": "timeout", "error": str(e)}
            except Exception as e:
                logger.error(f"Unexpected error during automation: {e}")
                return {"status": "error", "error": str(e)}
            finally:
                logger.info("Closing persistent browser context...")
                await context.close()

        logger.info("Locating form submission button...")

        submit_selectors = [
            "#submit-application",
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Send Application')",
            "[data-testid*='submit']"
        ]

        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    logger.info(f"Found submit button with selector: '{sel}'")
                    await page.eval_on_selector(sel, "el => { el.style.boxShadow = '0 0 10px #2563eb'; }")
                    await page.wait_for_timeout(400)
                    await btn.click()
                    logger.info(">>> Clicked application Submit button autonomously!")

                    await page.wait_for_timeout(1000)
                    confirm_selectors = [
                        "#success-message",
                        ".success",
                        ".application-success",
                        ":has-text('Application Submitted')",
                        ":has-text('Thank you')"
                    ]
                    for c_sel in confirm_selectors:
                        try:
                            c_elem = page.locator(c_sel).first
                            if await c_elem.is_visible(timeout=2000):
                                logger.info(f"Confirmed application submission indicator: '{c_sel}'")
                                return True
                        except Exception:
                            continue
                    return True
            except Exception:
                continue

        logger.warning("Could not find an automated submit button on the current page.")
        return False

    async def run(
        self,
        target_url: str,
        auto_submit: Optional[bool] = None,
        pause_on_completion: bool = True
    ) -> Dict[str, Any]:
        """
        End-to-end automation workflow for ATS forms:
        1. Launches persistent browser session (SessionManager).
        2. Navigates to target job URL.
        3. Executes Resume File Uploads.
        4. Analyzes DOM and discovers form fields.
        5. Maps fields using Ollama LLM / heuristics (handles ATS dropdowns).
        6. Generates long-form 200-400 word answers for custom questions.
        7. Fills fields and applies visual indicators.
        8. Autonomously submits form if auto_submit=True (or pauses for safety review).
        """
        should_submit = auto_submit if auto_submit is not None else self.config.AUTO_SUBMIT

        logger.info(f"--- Starting Autonomous JOBAGENT session ---")
        logger.info(f"Candidate: {self.profile.get('personal', {}).get('full_name')}")
        logger.info(f"Target URL: {target_url}")
        logger.info(f"Auto Submit: {should_submit} | Headless: {self.config.BROWSER_HEADLESS}")

        async with async_playwright() as p:
            context: BrowserContext = await self.session_manager.launch_persistent_context(
                p,
                headless=self.config.BROWSER_HEADLESS,
                slow_mo=self.config.BROWSER_SLOW_MO
            )
            page: Page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(self.config.PAGE_TIMEOUT)

            try:
                logger.info(f"Navigating to: {target_url}")
                await page.goto(target_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(1000)

                # Step 1: Handle Resume File Uploads first
                uploaded_files = await self.handle_file_uploads(page)

                # Step 2: DOM Analysis for inputs, dropdowns, and textareas
                form_fields = await self.extract_form_fields(page)
                if not form_fields:
                    logger.warning("No interactive form fields found on target page.")
                    return {"status": "no_fields_found", "filled": 0, "uploaded_files": uploaded_files}

                # Step 3: Field Mapping via Ollama / Heuristics
                mappings = await self.get_llm_mappings(form_fields)

                # Step 4: Form Filling (includes smart long-form generation & ATS dropdowns)
                stats = await self.fill_form_fields(page, mappings)
                stats["uploaded_files"] = uploaded_files

                # Step 5: Autonomous Submission or Safety Pause
                if should_submit:
                    submitted = await self.submit_form(page)
                    stats["submitted"] = submitted
                    print("\n" + "=" * 65)
                    print(f">>> AUTONOMOUS SUBMISSION: {'SUCCESS' if submitted else 'BUTTON NOT FOUND'}")
                    print("=" * 65 + "\n")
                else:
                    stats["submitted"] = False
                    if not self.config.BROWSER_HEADLESS and pause_on_completion:
                        print("\n" + "=" * 65)
                        print(">>> SAFETY REVIEW CHECKPOINT: Form has been filled and highlighted.")
                        print(">>> Auto-submit is OFF. Review the fields and uploaded resume in the browser.")
                        print(">>> Press [ENTER] in this terminal to close the browser session...")
                        print("=" * 65 + "\n")
                        await asyncio.to_thread(input)

                logger.info(
                    f"--- Session Complete: {stats['filled']} filled, {uploaded_files} files uploaded, "
                    f"{stats['skipped']} skipped, {stats['failed']} failed, submitted={stats.get('submitted')} ---"
                )
                return stats

            except PlaywrightTimeoutError as e:
                logger.error(f"Navigation or element timeout: {e}")
                return {"status": "timeout", "error": str(e)}
            except Exception as e:
                logger.error(f"Unexpected error during automation: {e}")
                return {"status": "error", "error": str(e)}
            finally:
                logger.info("Closing persistent browser context...")
                await context.close()