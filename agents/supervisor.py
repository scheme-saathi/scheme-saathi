"""Supervisor Agent: Input/Output guardrails and intelligent routing.

The supervisor acts as a gatekeeper with three layers:
1. INPUT GUARDRAILS: Validate user requests (language, intent, sensitive data)
2. ROUTING: Decide which specialist agent to invoke
3. OUTPUT GUARDRAILS: Validate specialist responses before returning to user

This ensures safe, controlled information flow across all agents.

 Unified Classification Strategy:
- Primary: configured OpenRouter model (language + intent in single call)
- Fallback: Character-based language + keyword intent detection (<1ms)
- Hybrid approach ensures resilience if API is unavailable
"""

import json
import logging
import os
import re
import time
from typing import Any, TypedDict

import requests
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, ValidationError

from agents.base import StructuredGPTAgent
from agents.contracts import Intent, Language, SupervisorInput, SupervisorPlan
from agents.persona_validator import (
    PersonaValidationError,
    SensitivePatternDetector,
)

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1"
SUPERVISOR_MODEL_ENV = "SUPERVISOR_MODEL"
ROUTER_MODEL_ENV = "ROUTER_MODEL"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"


class ClassificationResult(TypedDict):
    """Result of unified language + intent classification."""

    intent: Intent
    language: Language


class ValidationResult(BaseModel):
    """Result of validation check."""

    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    language: Language = "unknown"
    intent: Intent = "other"
    masked_content: str | None = None


class RateLimitTracker:
    """Simple in-memory rate limiter per household."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: dict[str, list[float]] = {}

    def is_allowed(self, actor_id: str) -> bool:
        """Check if actor is within rate limit."""
        current_time = time.time()
        if actor_id not in self.requests:
            self.requests[actor_id] = []

        # Clean old requests outside window
        self.requests[actor_id] = [
            t for t in self.requests[actor_id]
            if current_time - t < self.window_seconds
        ]

        # Check limit
        if len(self.requests[actor_id]) >= self.max_requests:
            return False

        # Record this request
        self.requests[actor_id].append(current_time)
        return True


class UnifiedRouter:
    """Unified language + intent classification via OpenRouter.
    
    Extracts both language and intent in a single API call to minimize latency
    and API costs. Includes automatic fallback to character-based detection
    and keyword matching if API is unavailable.
    """

    # Character set ranges for language detection (fallback)
    DEVANAGARI_RANGE = r"[\u0900-\u097F]"  # Hindi/Marathi
    MARATHI_SPECIFIC = r"[\u0950-\u0954]"  # Marathi-specific chars

    UNIFIED_PROMPT = """You are a unified classification and language routing hub for a government scheme chatbot.
Analyze the incoming text (which may be in English, Hindi, Marathi, Hinglish, or Roman Marathi).

1. EXTRACT INTENT:
- 'discover': Broad program exploration, finding out what schemes exist or what they qualify for.
- 'eligibility': Specific age/income/criteria checking or asking 'am I eligible'.
- 'documents': Asking about documentation requirements, required cards, or forms.
- 'application': Asking how to apply, registration protocols, or starting an onboarding application.
- 'follow_up': Tracking an application status or providing a reference ID token.
- 'other': Casual greetings, out-of-scope conversation, or unparseable input.

2. EXTRACT RESPONSE LANGUAGE:
Determine the user's primary intended language layout. Treat colloquial Roman text
(e.g., 'kya haal hai' -> 'hi', 'mala sang' -> 'mr') appropriately.
- 'en': English
- 'hi': Hindi
- 'mr': Marathi

Respond ONLY with a valid, raw JSON object containing the keys 'intent' and 'language'."""

    def __init__(self):
        self.openrouter_api_key = os.getenv(OPENROUTER_API_KEY_ENV)
        self.model = os.getenv(ROUTER_MODEL_ENV, "").strip() or os.getenv(SUPERVISOR_MODEL_ENV, "").strip()
        self.api_available = bool(self.openrouter_api_key and self.model)

        if self.api_available:
            logger.info("OpenRouter configured for unified classification")
        else:
            logger.warning(
                "OpenRouter API key or classifier model not configured. "
                "Will use character-based language detection + keyword intent matching."
            )

    def classify(self, text: str) -> ClassificationResult:
        """Classify language and intent in a single API call with fallback.
        
        Strategy:
        1. Try unified classification via the configured OpenRouter model
        2. On failure: Fall back to character-based + keyword methods
        3. Always returns valid ClassificationResult
        
        Args:
            text: Input text to classify
            
        Returns:
            ClassificationResult with intent and language
        """
        # Try unified API if available
        if self.api_available:
            result = self._classify_with_api(text)
            if result is not None:
                return result

        # Fallback to local methods
        return self._classify_with_fallback(text)

    def _classify_with_api(self, text: str) -> ClassificationResult | None:
        """Try unified classification via the configured OpenRouter model.
        
        Args:
            text: Input text to classify
            
        Returns:
            ClassificationResult if successful, None if API fails
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "HTTP-Referer": "https://github.com/scheme-saathi",
                "X-Title": "Scheme Saathi Unified Router",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": self.UNIFIED_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": text,
                    }
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,  # Deterministic for routing stability
                "max_tokens": 30,
            }

            response = requests.post(
                f"{OPENROUTER_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=10,  # 10 second timeout
            )

            if response.status_code != 200:
                logger.warning(
                    f"OpenRouter returned status {response.status_code}: {response.text}"
                )
                return None

            data = response.json()

            if not data.get("choices") or not data["choices"][0].get("message"):
                logger.debug("OpenRouter returned unexpected response structure")
                return None

            # Parse JSON response
            content = data["choices"][0]["message"]["content"]
            result_dict = json.loads(content)

            intent = result_dict.get("intent", "other")
            language = result_dict.get("language", "en")

            # Validate schema
            valid_intents = {"discover", "eligibility", "documents", "application", "follow_up", "other"}
            valid_languages = {"en", "hi", "mr"}

            if intent not in valid_intents:
                intent = "other"
            if language not in valid_languages:
                language = "en"

            logger.debug(f"Unified router classified - intent: {intent}, language: {language}")

            return {
                "intent": intent,  # type: ignore
                "language": language,  # type: ignore
            }

        except requests.exceptions.Timeout:
            logger.warning("Unified router timed out. Using fallback.")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Unified router API failed: {e}. Using fallback.")
            return None
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse unified router response: {e}. Using fallback.")
            return None

    def _classify_with_fallback(self, text: str) -> ClassificationResult:
        """Fallback to local character-based and keyword methods.
        
        Args:
            text: Input text to classify
            
        Returns:
            ClassificationResult with best-effort classification
        """
        language = self._detect_language_fallback(text)
        intent = self._classify_intent_fallback(text)

        return {
            "intent": intent,
            "language": language,
        }

    def _detect_language_fallback(self, text: str) -> Language:
        """Detect language from character set (fallback method).
        
        Args:
            text: Input text
            
        Returns:
            Language: "en", "hi", "mr", or "unknown"
        """
        devanagari_count = len(re.findall(self.DEVANAGARI_RANGE, text))
        total_chars = len(text)

        if total_chars == 0:
            return "unknown"

        devanagari_ratio = devanagari_count / total_chars

        if devanagari_ratio > 0.5:
            # Likely Hindi or Marathi - check for Marathi-specific chars
            if re.search(self.MARATHI_SPECIFIC, text):
                return "mr"
            return "hi"

        # Check for English (Latin characters)
        latin_count = len(re.findall(r"[a-zA-Z]", text))
        latin_ratio = latin_count / total_chars

        if latin_ratio > 0.5:
            return "en"

        return "unknown"

    def _classify_intent_fallback(self, text: str) -> Intent:
        """Classify intent from keywords (fallback method).
        
        Args:
            text: Input text
            
        Returns:
            Intent: One of the valid intent types
        """
        text_lower = text.lower()

        # Discover intent (most specific - "which schemes")
        if any(
            kw in text_lower
            for kw in [
                "which schemes",
                "what schemes",
                "कौन सी योजना",
                "कौन सी योजनाएं",
                "कौन सा योजना",
                "konsi yojana",
                "kaun si yojana",
                "कोणत्या योजना",
                "कोणत्या योजनांचे",
            ]
        ):
            return "discover"

        # Eligibility intent
        if any(
            kw in text_lower
            for kw in [
                "am i eligible",
                "eligibility",
                "eligible for",
                "क्या मैं पात्र हूँ",
                "पात्र हूँ",
                "पात्रता",
                "पात्र",
                "eligibility criteria",
                "requirements",
                "qualify",
                "kya main patra hoon",
                "मी पात्र आहे",
                "पात्र आहे",
                "मी योग्य आहे",
            ]
        ):
            return "eligibility"

        # Documents intent
        if any(
            kw in text_lower
            for kw in [
                "documents",
                "papers",
                "forms",
                "documents required",
                "documents needed",
                "दस्तावेज",
                "कागजात",
                "फार्म",
                "दस्तावेज़",
                "documents kya",
                "dastavez",
                "कागज",
                "दस्तावेज़",
                "कागजात लागतात",
                "कोणते कागदपत्र",
            ]
        ):
            return "documents"

        # Application intent
        if any(
            kw in text_lower
            for kw in [
                "apply",
                "application",
                "register",
                "आवेदन",
                "आवेदन करना",
                "आवेदन करूँ",
                "apply kaise",
                "kaise apply",
                "आवेदन कैसे करें",
                "अर्ज करायचे",
                "अर्ज",
                "नोंदणी",
                "नोंदणी करायचे",
                "रजिस्ट्रेशन",
                "रजिस्ट्रेशन कैसे करें",
            ]
        ):
            return "application"

        # Follow-up intent
        if any(
            kw in text_lower
            for kw in [
                "status",
                "reference",
                "application status",
                "track",
                "स्थिति",
                "संदर्भ",
                "आवेदन की स्थिति",
                "referral id",
                "reference id",
                "अर्जाची स्थिती",
                "status check",
                "track application",
            ]
        ):
            return "follow_up"

        # Default to other
        return "other"


class InputValidator:
    """Validates user input before reaching specialist agents."""

    def __init__(self, rate_limiter: RateLimitTracker | None = None, router: UnifiedRouter | None = None):
        self.rate_limiter = rate_limiter or RateLimitTracker()
        self.router = router or UnifiedRouter()

    def validate_request(
        self, request: str, actor_id: str | None = None, is_reply: bool = False
    ) -> ValidationResult:
        """Validate user request comprehensively.
        
        Performs:
        1. Empty/length checks
        2. Sensitive data detection
        3. Language + intent classification (unified)
        4. Rate limiting
        
        Args:
            request: User input text
            actor_id: Optional identifier for rate limiting
            is_reply: The text answers a pending question, so a short answer is allowed
                and it is not classified
            
        Returns:
            ValidationResult with all checks and classifications
        """
        errors = []
        warnings = []

        # 1. Empty check
        if not request or not request.strip():
            errors.append("Request cannot be empty")
            return ValidationResult(passed=False, errors=errors)

        # 2. Length check
        if len(request) > 5000:
            errors.append("Request too long (max 5000 characters)")
        if len(request) < 5 and not is_reply:
            errors.append("Request too short (min 5 characters)")

        # 3. Detect sensitive patterns
        sensitive_type = SensitivePatternDetector.detect_sensitive_type(request)
        if sensitive_type:
            errors.append(
                f"Request contains sensitive information ({sensitive_type}). "
                "Please avoid sharing Aadhar, account numbers, or other sensitive data."
            )
            logger.warning("Sensitive data rejected in request.")
            return ValidationResult(passed=False, errors=errors, warnings=warnings)

        # 4. Unified classification (language + intent in single call)
        if is_reply:
            classification = {"language": "unknown", "intent": "other"}
        else:
            classification = self.router.classify(request)
        language = classification["language"]
        intent = classification["intent"]

        if language == "unknown" and not is_reply:
            warnings.append("Language could not be detected with confidence")

        # 5. Rate limiting (if actor_id provided)
        if actor_id and not self.rate_limiter.is_allowed(actor_id):
            errors.append("Too many requests. Please wait before sending more.")

        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            language=language,
            intent=intent,
        )


class RoutingEngine:
    """Routes classified requests to appropriate specialist agents."""

    def determine_route(
        self,
        intent: Intent,
        has_clarifying_questions: bool = False,
        has_prior_facts: bool = False,
    ) -> SupervisorPlan:
        """Determine which agent should handle this request.
        
        Routing logic:
        - discover → intake (gather household facts)
        - eligibility + no facts → intake (collect facts first)
        - eligibility + has facts → eligibility_agent
        - documents → document_checker
        - application → intake (full info collection)
        - follow_up → respond (status tracking)
        - other → respond (general chatbot)
        
        If clarifying questions exist, pause and ask user.
        
        Args:
            intent: Classified user intent
            has_clarifying_questions: If intake has follow-up questions
            has_prior_facts: If we have household facts on file
            
        Returns:
            SupervisorPlan with next agent and reason
        """
        # If clarifying questions exist, pause and ask user
        if has_clarifying_questions:
            return SupervisorPlan(
                next_agent="respond",  # type: ignore
                reason="Clarifying questions needed from user before proceeding",
            )

        next_agent = "respond"
        reason = ""

        if intent == "discover":
            next_agent = "intake"
            reason = "User exploring available schemes - collect household facts for personalized discovery"

        elif intent == "eligibility":
            if has_prior_facts:
                next_agent = "eligibility"
                reason = "User asking eligibility - we have all needed facts, can check now"
            else:
                next_agent = "intake"
                reason = "User asking eligibility but we lack facts - collect info first"

        elif intent == "documents":
            next_agent = "document_checker"
            reason = "User asking about documentation requirements"

        elif intent == "application":
            next_agent = "intake"
            reason = "User wants to apply - collect complete household facts first"

        elif intent == "follow_up":
            next_agent = "respond"
            reason = "User checking application status or providing reference"

        else:  # other
            next_agent = "respond"
            reason = "General question or greeting - respond naturally"

        return SupervisorPlan(
            next_agent=next_agent,  # type: ignore
            reason=reason,
        )


# shortcut: phrase lists, covering en + common hi/mr wording; extend if reviews find misses.
# A claim is about the person or a relative ("you", "she", "your grandmother"); a criterion
# quoted for everyone ("Widows aged 40-79 can get Rs 300") names no one and stays allowed.
_PERSON = r"(?:you|she|he|your(?:\s+[a-z\-]+){1,2})"
# "get/receive/avail" counts only with a benefit after it: "you can get the form" is procedure.
_BENEFIT = (r"(?:pension|benefits?|assistance|subsidy|scholarships?|insurance|cover|loans?|card|money"
            r"|grant|allowance|stipend|amount|rs\.?|rupees|help|support|aid)")
_VERDICT = re.compile(
    rf"\b{_PERSON}\s+(?:can|could|will|may|might|should|would)\s+(?:also\s+|still\s+)?"
    rf"(?:join|qualify|be eligible|benefit|(?:get|receive|avail)\b(?:\s+\S+){{0,4}}?\s+{_BENEFIT})\b"
    rf"|\b{_PERSON}\s+(?:is|are|'re|'s)\s+(?:not\s+|also\s+)?(?:eligible|entitled|qualified)\b"
    rf"|\b{_PERSON}\s+(?:do not |don't |does not |doesn't )?qualif(?:y|ies)\b"
    r"|\b(?:you|application) (?:is|are|has been|have been) approved\b"
)
# "Yes, there is a pension for your grandmother": a yes/no answer about the person.
_YES_NO_ABOUT_PERSON = re.compile(r"^(?:yes|no)\b.*\b(?:you|your|she|her|he|him)\b")
_HI_PERSON = ("आप", "आपको", "आपके", "आपकी", "उन्हें", "उनको", "वह", "वे")
_HI_VERDICT = ("पात्र", "हकदार", "लाभ ले सकत")
_HI_GET = ("मिल सकत", "मिलेग", "मिल जाएग")
_HI_BENEFIT = ("पेंशन", "लाभ", "सहायता", "राशि", "रुपये", "सब्सिडी", "छात्रवृत्ति", "कार्ड", "बीमा", "ऋण", "मदद")
_MR_PERSON = ("तुम्ही", "तुम्हाला", "तुमच्या", "त्यांना", "तिला", "त्याला")
_MR_VERDICT = ("पात्र", "हक्कदार", "लाभ घेऊ शकत")
_MR_GET = ("मिळू शकत", "मिळेल")
_MR_BENEFIT = ("पेन्शन", "लाभ", "मदत", "सहाय्य", "रक्कम", "रुपये", "अनुदान", "शिष्यवृत्ती", "कार्ड", "विमा", "कर्ज")
_SENTENCE = re.compile(r"(?<=[.!?।])\s+|\n+")


def _decides_eligibility(text: str) -> bool:
    """A personal verdict ("you are eligible", "your mother can get it"), not a question or
    a criterion quoted for everyone."""
    for sentence in _SENTENCE.split(text.strip()):
        sentence = sentence.strip()
        if not sentence or sentence.endswith("?"):
            continue
        lower = sentence.lower()
        if _VERDICT.search(lower) or _YES_NO_ABOUT_PERSON.search(lower):
            return True
        words = set(re.findall(r"[\u0900-\u097F]+", sentence))
        for person, verdict, get, benefit in (
            (_HI_PERSON, _HI_VERDICT, _HI_GET, _HI_BENEFIT),
            (_MR_PERSON, _MR_VERDICT, _MR_GET, _MR_BENEFIT),
        ):
            if words & set(person) and (
                any(v in sentence for v in verdict)
                or (any(g in sentence for g in get) and any(b in sentence for b in benefit))
            ):
                return True
    return False


# shortcut: phrase lists for en + common hi/mr wording; extend from routing misses in evaluation.
# "Can she get a pension?", "Is there a scheme for me?", "Which schemes can I join?" ask about the
# person's own eligibility, so intake and the rule engine must answer them, not scheme Q&A.
_ASKER = r"(?:i|we|she|he|they|my(?:\s+[a-z\-]+){1,2}|our(?:\s+[a-z\-]+){1,2})"
_OWN_ELIGIBILITY = re.compile(
    rf"\b(?:can|could|will|would|do|does|may|should)\s+{_ASKER}\s+(?:still\s+|also\s+|ever\s+)?"
    r"(?:get|join|qualify|be eligible|receive|avail|claim|benefit)\b"
    rf"|\b(?:am|is|are)\s+{_ASKER}\s+(?:still\s+|also\s+)?(?:eligible|entitled|qualified)\b"
    r"|\bfor (?:me|us|her|him|them|my(?:\s+[a-z\-]+){1,2}|our(?:\s+[a-z\-]+){1,2})\b"
    rf"|\b(?:what|which)\b[^.?!]*\b(?:can|could|should|do|will)\s+{_ASKER}\s+(?:get|join|apply|claim|receive)\b"
)
_PROCEDURAL_START = re.compile(r"^\s*(?:how|where|when|what documents|which documents)\b")
_HI_ASKER = ("मुझे", "मेरे", "मेरी", "मेरा", "हमें", "हमारे", "उन्हें", "उनको", "उसे", "उसके", "मैं")
_HI_SEEK = ("मिल सकत", "मिलेग", "मिलती", "मिलता", "पात्र", "जुड़ सकत", "ले सकत", "मेरे लिए", "हमारे लिए")
_MR_ASKER = ("मला", "माझ्या", "माझी", "माझे", "आम्हाला", "तिला", "त्याला", "त्यांना", "मी")
_MR_SEEK = ("मिळू शकत", "मिळेल", "मिळते", "मिळतो", "पात्र", "सामील होऊ शकत", "घेऊ शकत")


def asks_about_own_eligibility(text: str) -> bool:
    """Does the message ask whether the person, or someone they speak for, can get a benefit?

    A factual question about a scheme ("What is the age limit for APY?", "How do I apply?")
    is not one, even when it says "I".
    """
    for sentence in re.split(r"(?<=[.!?।])\s+|\n+", text.strip()):
        lower = sentence.lower()
        if not lower or _PROCEDURAL_START.search(lower):
            continue
        if _OWN_ELIGIBILITY.search(lower):
            return True
        words = set(re.findall(r"[\u0900-\u097F]+", sentence))
        for askers, seeks in ((_HI_ASKER, _HI_SEEK), (_MR_ASKER, _MR_SEEK)):
            if (words & set(askers) or "मेरे लिए" in sentence) and any(s in sentence for s in seeks):
                return True
    return False


class OutputValidator:
    """Validates specialist agent responses before returning to user."""

    def validate_specialist_output(
        self, response: Any, agent_name: str, user_language: Language
    ) -> ValidationResult:
        """Validate output from specialist agents.
        
        Checks:
        1. Response structure matches agent's contract
        2. No sensitive data exposed
        3. Claims are properly cited (eligibility)
        4. No oversteps (e.g., eligibility agent claiming to approve)
        
        Args:
            response: Response from specialist agent
            agent_name: Name of the specialist agent
            user_language: User's language for error messages
            
        Returns:
            ValidationResult indicating if output is safe to return
        """
        errors = []
        warnings = []
        masked_content = None

        # 1. Empty response check
        if not response:
            errors.append("Agent returned empty response")
            return ValidationResult(
                passed=False,
                errors=errors,
                language=user_language,
            )

        # 2. Convert to string if needed
        response_text = str(response) if not isinstance(response, str) else response

        # 3. Check for sensitive data in output
        sensitive_type = SensitivePatternDetector.detect_sensitive_type(response_text)
        if sensitive_type:
            errors.append(f"Response contains sensitive information ({sensitive_type})")
            masked_content = "[Sensitive content removed]"
            logger.error("Agent %s exposed sensitive data (%s).", agent_name, sensitive_type)

        # 4. Agent-specific validation
        if agent_name == "intake":
            # Intake must return valid language and intent
            if isinstance(response, dict):
                lang = response.get("language", "unknown")
                if lang not in ["en", "hi", "mr", "unknown"]:
                    errors.append(f"Invalid language in response: {lang}")
            # Intake should collect facts, not make decisions. A word match blocked fair questions
            # such as "Is your institution approved by AICTE?", so only a personal verdict counts.
            if _decides_eligibility(response_text):
                errors.append("Intake agent should not make eligibility decisions")

        elif agent_name == "eligibility":
            # Eligibility must cite rules/clauses
            if "eligible" in response_text.lower():
                if not any(
                    kw in response_text.lower()
                    for kw in ["clause", "rule", "section", "according to", "per", "norms", "criteria"]
                ):
                    warnings.append(
                        "Eligibility claim lacks citation. Add clause/rule reference."
                    )

            # No overrides allowed
            if any(
                kw in response_text.lower()
                for kw in ["override", "approve", "granted", "exception"]
            ):
                if "override" in response_text.lower():
                    errors.append("Eligibility agent cannot override or make exceptions - only assess per rules")
                else:
                    errors.append("Eligibility agent cannot approve/grant - only assess per rules")

        elif agent_name == "document_checker":
            # authenticity_verified must be False (we can't verify authenticity)
            if isinstance(response, dict):
                if response.get("authenticity_verified") is True:
                    errors.append(
                        "Document Checker cannot verify authenticity - authenticity_verified must be False"
                    )

        elif agent_name == "scheme_info":
            # Quoting a scheme's criteria is fine; deciding the user's own eligibility is not.
            if _decides_eligibility(response_text):
                errors.append("Scheme answers must not decide the user's own eligibility")

        # 5. Response length sanity check
        if len(response_text) > 10000:
            warnings.append("Response very long (>10,000 chars) - may be excessive")

        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            language=user_language,
            masked_content=masked_content,
        )

    def get_user_friendly_error(
        self, validation_result: ValidationResult, language: Language
    ) -> str:
        """Convert technical errors to user-friendly messages.
        
        Args:
            validation_result: Validation result with errors
            language: User's language
            
        Returns:
            Friendly error message in user's language
        """
        if language == "hi":
            return "क्षमा करें, सिस्टम को प्रतिक्रिया देने में समस्या हुई। कृपया फिर से प्रयास करें।"
        elif language == "mr":
            return "क्षमा करा, सिस्टमला प्रतिक्रिया देने में समस्या हुई। कृपया पुन्हा प्रयत्न करा।"
        else:
            return "Sorry, there was an issue processing your request. Please try again."


SUPERVISOR_INSTRUCTIONS = """You are Scheme Saathi's Supervisor Agent - a gatekeeper for safe, controlled access.

Your job is to validate and route requests intelligently:

1. VALIDATE INPUT:
   - Reject requests with sensitive data (Aadhar, account numbers, etc.)
   - Classify intent: discover/eligibility/documents/application/follow_up
   - Detect language: English, Hindi, Marathi
   - Rate limit by household/actor

2. ROUTE INTELLIGENTLY:
   - Discover → Intake Agent (collect facts about household)
   - Eligibility check → Intake (if new) or Eligibility Agent (if facts known)
   - Documents needed → Document Checker Agent
   - Want to apply → Intake Agent first (collect all facts)
   - Status update → Respond (this is Phase 4, not yet available)
   - Factual question about a scheme (benefits, limits, how to apply) that does not ask to check
     the user's own eligibility → Respond with scheme_question true; it is answered from cited documents
   - A question whether the user or someone they speak for can get something is an eligibility
     check, not a scheme question: "Is there a widow pension for me?", "Can my mother get a pension?",
     "Which schemes can I join?", "मुझे कौन सी योजना मिल सकती है?", "मला कोणती योजना मिळू शकते?"
     → Intake, even when it names a scheme

3. VALIDATE OUTPUT:
   - Ensure specialist responses follow contracts
   - No sensitive data exposed in responses
   - Eligibility claims are cited with rule/clause references
   - No agent oversteps its boundaries

Rules you must follow:
- NEVER make eligibility decisions yourself; only route to Eligibility Agent
- NEVER override, approve, or reject applications; route to Application Agent
- NEVER claim authenticity of documents; route to Document Checker
- When input is invalid, explain briefly in user's language without exposing technical details
- Log all validation failures for security review
- If a specialist returns invalid output, ask it to fix or escalate to human reviewer
- When document_check is supplied, use that result to give a concise user-facing
  summary in reason and set next_agent to respond. Do not add findings or claim
  documents are authentic, valid, or verified.

You are the security layer. Your job is to prevent harm and ensure trust."""


class SupervisorAgent(StructuredGPTAgent[SupervisorInput, SupervisorPlan]):
    """Supervisor: Routes requests safely to specialist agents."""

    def __init__(self, model: BaseChatModel) -> None:
        super().__init__(
            model, SupervisorInput, SupervisorPlan, SUPERVISOR_INSTRUCTIONS
        )
        self.input_validator = InputValidator()
        self.routing_engine = RoutingEngine()
        self.output_validator = OutputValidator()

    def validate_input(
        self, request: str, actor_id: str | None = None, is_reply: bool = False
    ) -> ValidationResult:
        """Step 1: Validate user input."""
        return self.input_validator.validate_request(request, actor_id, is_reply)

    def route_request(
        self,
        intent: Intent,
        has_clarifying_questions: bool = False,
        has_prior_facts: bool = False,
    ) -> SupervisorPlan:
        """Step 2: Route to appropriate agent."""
        return self.routing_engine.determine_route(
            intent, has_clarifying_questions, has_prior_facts
        )

    def validate_output(
        self, response: Any, agent_name: str, user_language: Language
    ) -> ValidationResult:
        """Step 3: Validate specialist output."""
        return self.output_validator.validate_specialist_output(
            response, agent_name, user_language
        )

    def handle_validation_error(
        self, validation_result: ValidationResult, language: Language
    ) -> dict[str, Any]:
        """Convert validation errors to safe user response."""
        return {
            "status": "validation_error",
            "user_message": self.output_validator.get_user_friendly_error(
                validation_result, language
            ),
            "error_count": len(validation_result.errors),
            "logged_for_debugging": True,
        }
