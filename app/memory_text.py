"""Wording for the memory screens in English, Hindi and Marathi.

Hindi and Marathi are drafts: have a reviewer approve them before they are shown to citizens.
"""

from __future__ import annotations

LANGUAGES = {"en": "English", "hi": "हिंदी", "mr": "मराठी"}

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "language_label": "Language",
        "consent_heading": "Remember details for future visits? (optional)",
        "consent_notice": (
            "With your permission, Scheme Saathi can remember the household details listed below so "
            "you do not need to enter them again. Each detail has a retention period. You can use "
            "Scheme Saathi without saving anything, correct details later, or choose “Forget my "
            "data”. This does not delete applications already submitted to a government portal. "
            "Details you give about other people are used only for that check and are not saved."
        ),
        "retention_line": "{field}: asked again after {reconfirm} days, deleted after {expiry} days",
        "choice_facts": "Remember these household details",
        "choice_refs": "Save application references so I can track them later",
        "refs_note": (
            "Only the scheme, the application number, the date and whether it was for you or for "
            "someone else are kept, for {days} days. The status is always read from the portal."
        ),
        "leave_unticked": "Leave both boxes unticked to continue without remembering anything.",
        "memory_failed": "Your choice about remembering details could not be saved: {error}",
        "panel_button": "Saved details",
        "panel_title": "What Scheme Saathi remembers",
        "unavailable": "Remembering details is not available right now.",
        "facts_on": "Remembering household details: on",
        "facts_off": "Remembering household details: off",
        "refs_on": "Saving application references: on",
        "refs_off": "Saving application references: off",
        "turn_on": "Turn on",
        "turn_off": "Turn off and delete what was saved",
        "no_facts": "No household details are remembered.",
        "reconfirm_due": "Will be asked again at your next check",
        "until": "kept until {date}",
        "forget_one": "Forget",
        "applications_title": "My applications",
        "for_me": "For me",
        "for_others": "For other people",
        "for_family": "My family",
        "nickname_label": "Nickname (letters only, optional)",
        "nickname_save": "Save nickname",
        "family_remove": "Remove this person and their saved applications",
        "nickname_invalid": "A nickname can only use letters.",
        "operator_agreement": "The person I am helping agrees to this application being kept on my list for {days} days",
        "operator_agreement_help": (
            "Optional. Leave it unticked and nothing is kept; the application is still submitted. If ticked, only "
            "the application number, scheme and date are kept, with no personal details. The person's own "
            "\"Forget my data\" cannot reach it, but you can remove it from your list at any time."
        ),
        "operator_note": (
            "As an operator you keep no household details. When you approve an application, tick the box "
            "only if the person you are helping agrees to it being kept on your list."
        ),
        "none_saved": "No applications are saved.",
        "check_status": "Check status",
        "status_is": "Status at the portal: {status}",
        "not_at_portal": "The portal does not have this application any more.",
        "remove": "Remove from list",
        "forget_all": "Forget my data",
        "forget_confirm": (
            "I understand this deletes everything saved for my household: remembered details, saved "
            "applications, conversations and uploaded documents."
        ),
        "forget_note": "This does not delete applications already submitted to a government portal.",
        "forget_done": (
            "Your remembered details, saved applications, conversations and uploaded documents were deleted."
        ),
        "checking_for_self": "Checking for: you",
        "checking_for_other": "Checking for: your {relation}",
        "checking_for_someone": "Checking for: someone else",
        "applying_for_self": "Applying for: you",
        "applying_for_other": "Applying for: your {relation}",
        "applying_for_someone": "Applying for: someone else",
        "remembered_from_before": (
            "Filled in from your last visit: {fields}. Please check that they are still correct."
        ),
        "yes": "Yes",
        "no": "No",
    },
    "hi": {
        "language_label": "भाषा",
        "consent_heading": "अगली बार के लिए जानकारी याद रखें? (वैकल्पिक)",
        "consent_notice": (
            "आपकी अनुमति से, स्कीम साथी नीचे दी गई परिवार की जानकारी याद रख सकता है, ताकि आपको उसे "
            "दोबारा न भरना पड़े। हर जानकारी के लिए रखने की एक अवधि है। आप कुछ भी सहेजे बिना भी स्कीम "
            "साथी का उपयोग कर सकते हैं, बाद में जानकारी सुधार सकते हैं, या “मेरा डेटा भूल जाएँ” चुन "
            "सकते हैं। इससे किसी सरकारी पोर्टल पर पहले से जमा किए गए आवेदन नहीं हटते। दूसरे लोगों के "
            "बारे में आप जो जानकारी देते हैं, वह केवल उसी जाँच के लिए इस्तेमाल होती है और सहेजी नहीं जाती।"
        ),
        "retention_line": "{field}: {reconfirm} दिन बाद दोबारा पूछा जाएगा, {expiry} दिन बाद हटा दिया जाएगा",
        "choice_facts": "परिवार की ये जानकारियाँ याद रखें",
        "choice_refs": "आवेदन के संदर्भ सहेजें ताकि मैं बाद में उन्हें ट्रैक कर सकूँ",
        "refs_note": (
            "केवल योजना, आवेदन संख्या, तारीख और यह कि आवेदन आपके लिए था या किसी और के लिए, {days} दिन "
            "तक रखा जाता है। स्थिति हमेशा पोर्टल से ही पढ़ी जाती है।"
        ),
        "leave_unticked": "कुछ भी याद रखे बिना आगे बढ़ने के लिए दोनों बॉक्स खाली छोड़ दें।",
        "memory_failed": "जानकारी याद रखने का आपका चुनाव सहेजा नहीं जा सका: {error}",
        "panel_button": "सहेजी गई जानकारी",
        "panel_title": "स्कीम साथी क्या याद रखता है",
        "unavailable": "जानकारी याद रखने की सुविधा अभी उपलब्ध नहीं है।",
        "facts_on": "परिवार की जानकारी याद रखना: चालू",
        "facts_off": "परिवार की जानकारी याद रखना: बंद",
        "refs_on": "आवेदन के संदर्भ सहेजना: चालू",
        "refs_off": "आवेदन के संदर्भ सहेजना: बंद",
        "turn_on": "चालू करें",
        "turn_off": "बंद करें और सहेजा गया हटाएँ",
        "no_facts": "परिवार की कोई जानकारी याद नहीं रखी गई है।",
        "reconfirm_due": "अगली जाँच में दोबारा पूछा जाएगा",
        "until": "{date} तक रखा जाएगा",
        "forget_one": "भूल जाएँ",
        "applications_title": "मेरे आवेदन",
        "for_me": "मेरे लिए",
        "for_others": "दूसरे लोगों के लिए",
        "for_family": "मेरा परिवार",
        "nickname_label": "उपनाम (केवल अक्षर, वैकल्पिक)",
        "nickname_save": "उपनाम सहेजें",
        "family_remove": "इस व्यक्ति और उनके सहेजे गए आवेदन हटाएँ",
        "nickname_invalid": "उपनाम में केवल अक्षर हो सकते हैं।",
        "operator_agreement": (
            "जिस व्यक्ति की मैं मदद कर रहा/रही हूँ, वह इस आवेदन को {days} दिनों तक मेरी सूची में रखे जाने के लिए सहमत है"
        ),
        "operator_agreement_help": (
            "वैकल्पिक। टिक न करने पर कुछ भी नहीं रखा जाएगा; आवेदन फिर भी जमा होगा। टिक करने पर केवल आवेदन संख्या, योजना और "
            "तारीख रखी जाती है, कोई व्यक्तिगत जानकारी नहीं। उस व्यक्ति का अपना \"मेरा डेटा भूल जाएँ\" इस तक नहीं पहुँच सकता, पर "
            "आप इसे कभी भी अपनी सूची से हटा सकते हैं।"
        ),
        "operator_note": (
            "ऑपरेटर के रूप में आप परिवार की कोई जानकारी नहीं रखते। आवेदन मंज़ूर करते समय, बॉक्स तभी टिक करें जब आप "
            "जिस व्यक्ति की मदद कर रहे हैं वह उसे आपकी सूची में रखे जाने के लिए सहमत हो।"
        ),
        "none_saved": "कोई आवेदन सहेजा नहीं गया है।",
        "check_status": "स्थिति देखें",
        "status_is": "पोर्टल पर स्थिति: {status}",
        "not_at_portal": "पोर्टल पर यह आवेदन अब नहीं मिल रहा है।",
        "remove": "सूची से हटाएँ",
        "forget_all": "मेरा डेटा भूल जाएँ",
        "forget_confirm": (
            "मैं समझता/समझती हूँ कि इससे मेरे परिवार के लिए सहेजी गई सारी जानकारी, सहेजे गए आवेदन, बातचीत और "
            "अपलोड किए गए दस्तावेज़ हट जाएँगे।"
        ),
        "forget_note": "इससे किसी सरकारी पोर्टल पर पहले से जमा किए गए आवेदन नहीं हटते।",
        "forget_done": (
            "आपके परिवार की सहेजी गई जानकारी, सहेजे गए आवेदन, बातचीत और अपलोड किए गए दस्तावेज़ हटा दिए गए।"
        ),
        "checking_for_self": "जाँच किसके लिए: आप",
        "checking_for_other": "जाँच किसके लिए: आपके {relation}",
        "checking_for_someone": "जाँच किसके लिए: किसी और के लिए",
        "applying_for_self": "आवेदन किसके लिए: आप",
        "applying_for_other": "आवेदन किसके लिए: आपके {relation}",
        "applying_for_someone": "आवेदन किसके लिए: किसी और के लिए",
        "remembered_from_before": (
            "पिछली बार की जानकारी से भरा गया: {fields}। कृपया जाँच लें कि वह अब भी सही है।"
        ),
        "yes": "हाँ",
        "no": "नहीं",
    },
    "mr": {
        "language_label": "भाषा",
        "consent_heading": "पुढील भेटींसाठी माहिती लक्षात ठेवायची? (पर्यायी)",
        "consent_notice": (
            "तुमच्या परवानगीने, स्कीम साथी खाली दिलेली कुटुंबाची माहिती लक्षात ठेवू शकतो, म्हणजे तुम्हाला "
            "ती पुन्हा भरावी लागणार नाही. प्रत्येक माहितीसाठी ठेवण्याचा कालावधी आहे. काहीही जतन न करताही "
            "तुम्ही स्कीम साथी वापरू शकता, नंतर माहिती दुरुस्त करू शकता, किंवा “माझा डेटा विसरा” निवडू "
            "शकता. यामुळे सरकारी पोर्टलवर आधीच सादर केलेले अर्ज हटत नाहीत. इतर लोकांबद्दल तुम्ही दिलेली "
            "माहिती फक्त त्याच तपासणीसाठी वापरली जाते आणि जतन केली जात नाही."
        ),
        "retention_line": "{field}: {reconfirm} दिवसांनी पुन्हा विचारले जाईल, {expiry} दिवसांनी हटवले जाईल",
        "choice_facts": "कुटुंबाची ही माहिती लक्षात ठेवा",
        "choice_refs": "अर्जाचे संदर्भ जतन करा, म्हणजे मी ते नंतर तपासू शकेन",
        "refs_note": (
            "फक्त योजना, अर्ज क्रमांक, तारीख आणि अर्ज तुमच्यासाठी होता की इतर कोणासाठी, हे {days} दिवस "
            "ठेवले जाते. स्थिती नेहमी पोर्टलवरूनच वाचली जाते."
        ),
        "leave_unticked": "काहीही लक्षात न ठेवता पुढे जाण्यासाठी दोन्ही चौकोन रिकामे ठेवा.",
        "memory_failed": "माहिती लक्षात ठेवण्याबद्दलची तुमची निवड जतन करता आली नाही: {error}",
        "panel_button": "जतन केलेली माहिती",
        "panel_title": "स्कीम साथी काय लक्षात ठेवतो",
        "unavailable": "माहिती लक्षात ठेवण्याची सुविधा सध्या उपलब्ध नाही.",
        "facts_on": "कुटुंबाची माहिती लक्षात ठेवणे: चालू",
        "facts_off": "कुटुंबाची माहिती लक्षात ठेवणे: बंद",
        "refs_on": "अर्जाचे संदर्भ जतन करणे: चालू",
        "refs_off": "अर्जाचे संदर्भ जतन करणे: बंद",
        "turn_on": "चालू करा",
        "turn_off": "बंद करा आणि जतन केलेले हटवा",
        "no_facts": "कुटुंबाची कोणतीही माहिती लक्षात ठेवलेली नाही.",
        "reconfirm_due": "पुढील तपासणीत पुन्हा विचारले जाईल",
        "until": "{date} पर्यंत ठेवले जाईल",
        "forget_one": "विसरा",
        "applications_title": "माझे अर्ज",
        "for_me": "माझ्यासाठी",
        "for_others": "इतर लोकांसाठी",
        "for_family": "माझे कुटुंब",
        "nickname_label": "टोपणनाव (फक्त अक्षरे, ऐच्छिक)",
        "nickname_save": "टोपणनाव जतन करा",
        "family_remove": "ही व्यक्ती आणि त्यांचे जतन केलेले अर्ज काढा",
        "nickname_invalid": "टोपणनावात फक्त अक्षरे असू शकतात.",
        "operator_agreement": (
            "मी ज्या व्यक्तीला मदत करत आहे ती व्यक्ती हा अर्ज {days} दिवस माझ्या यादीत ठेवण्यास सहमत आहे"
        ),
        "operator_agreement_help": (
            "ऐच्छिक. टिक न केल्यास काहीही ठेवले जाणार नाही; अर्ज तरीही सादर होईल. टिक केल्यास फक्त अर्ज क्रमांक, योजना आणि "
            "तारीख ठेवली जाते, कोणतीही वैयक्तिक माहिती नाही. त्या व्यक्तीचे स्वतःचे \"माझा डेटा विसरा\" तिथपर्यंत पोहोचू शकत नाही, "
            "पण तुम्ही ते कधीही तुमच्या यादीतून काढू शकता."
        ),
        "operator_note": (
            "ऑपरेटर म्हणून तुम्ही कुटुंबाची कोणतीही माहिती ठेवत नाही. अर्ज मंजूर करताना, तुम्ही ज्या व्यक्तीला मदत "
            "करत आहात ती व्यक्ती तो तुमच्या यादीत ठेवण्यास सहमत असेल तरच बॉक्स टिक करा."
        ),
        "none_saved": "कोणताही अर्ज जतन केलेला नाही.",
        "check_status": "स्थिती पहा",
        "status_is": "पोर्टलवरील स्थिती: {status}",
        "not_at_portal": "हा अर्ज पोर्टलवर आता सापडत नाही.",
        "remove": "यादीतून काढा",
        "forget_all": "माझा डेटा विसरा",
        "forget_confirm": (
            "मला समजले आहे की यामुळे माझ्या कुटुंबाची जतन केलेली माहिती, जतन केलेले अर्ज, संभाषणे आणि अपलोड "
            "केलेली कागदपत्रे हटवली जातील."
        ),
        "forget_note": "यामुळे सरकारी पोर्टलवर आधीच सादर केलेले अर्ज हटत नाहीत.",
        "forget_done": (
            "तुमच्या कुटुंबाची जतन केलेली माहिती, जतन केलेले अर्ज, संभाषणे आणि अपलोड केलेली कागदपत्रे हटवली आहेत."
        ),
        "checking_for_self": "तपासणी कोणासाठी: तुम्ही",
        "checking_for_other": "तपासणी कोणासाठी: तुमच्या {relation}",
        "checking_for_someone": "तपासणी कोणासाठी: इतर कोणासाठी",
        "applying_for_self": "अर्ज कोणासाठी: तुम्ही",
        "applying_for_other": "अर्ज कोणासाठी: तुमच्या {relation}",
        "applying_for_someone": "अर्ज कोणासाठी: इतर कोणासाठी",
        "remembered_from_before": (
            "मागील भेटीतील माहितीवरून भरले: {fields}. कृपया ती अजूनही बरोबर आहे का ते तपासा."
        ),
        "yes": "होय",
        "no": "नाही",
    },
}

FIELD_NAMES: dict[str, dict[str, str]] = {
    "en": {
        "is_maharashtra_resident": "Resident of Maharashtra",
        "is_indian_citizen": "Indian citizen",
        "age": "Age",
        "annual_income": "Annual income",
        "annual_family_income": "Annual family income",
        "is_woman_or_girl": "Woman or girl",
        "marital_status": "Marital status",
        "household_below_bpl": "Household below poverty line (BPL)",
        "ration_card_type": "Ration card type",
    },
    "hi": {
        "is_maharashtra_resident": "महाराष्ट्र के निवासी",
        "is_indian_citizen": "भारतीय नागरिक",
        "age": "आयु",
        "annual_income": "वार्षिक आय",
        "annual_family_income": "वार्षिक पारिवारिक आय",
        "is_woman_or_girl": "महिला या लड़की",
        "marital_status": "वैवाहिक स्थिति",
        "household_below_bpl": "गरीबी रेखा से नीचे का परिवार (BPL)",
        "ration_card_type": "राशन कार्ड का प्रकार",
    },
    "mr": {
        "is_maharashtra_resident": "महाराष्ट्राचे रहिवासी",
        "is_indian_citizen": "भारतीय नागरिक",
        "age": "वय",
        "annual_income": "वार्षिक उत्पन्न",
        "annual_family_income": "वार्षिक कौटुंबिक उत्पन्न",
        "is_woman_or_girl": "महिला किंवा मुलगी",
        "marital_status": "वैवाहिक स्थिती",
        "household_below_bpl": "दारिद्र्यरेषेखालील कुटुंब (BPL)",
        "ration_card_type": "शिधापत्रिकेचा प्रकार",
    },
}


RELATION_NAMES: dict[str, dict[str, str]] = {
    "en": {
        "mother": "Mother",
        "father": "Father",
        "grandmother": "Grandmother",
        "grandfather": "Grandfather",
        "son": "Son",
        "daughter": "Daughter",
        "wife": "Wife",
        "husband": "Husband",
    },
    "hi": {
        "mother": "माँ",
        "father": "पिता",
        "grandmother": "दादी/नानी",
        "grandfather": "दादा/नाना",
        "son": "बेटा",
        "daughter": "बेटी",
        "wife": "पत्नी",
        "husband": "पति",
    },
    "mr": {
        "mother": "आई",
        "father": "वडील",
        "grandmother": "आजी",
        "grandfather": "आजोबा",
        "son": "मुलगा",
        "daughter": "मुलगी",
        "wife": "पत्नी",
        "husband": "पती",
    },
}


def text(language: str, key: str, **values: object) -> str:
    """The wording for `key` in the language, falling back to English; `values` fill its blanks."""
    table = TEXT.get(language) or TEXT["en"]
    template = table.get(key) or TEXT["en"][key]
    return template.format(**values) if values else template


def relation_name(language: str, relation: str) -> str:
    """A family relation in the person's language, falling back to English and then the word itself."""
    names = RELATION_NAMES.get(language) or RELATION_NAMES["en"]
    return names.get(relation) or RELATION_NAMES["en"].get(relation) or relation.capitalize()


def field_name(language: str, field: str) -> str:
    """A reader-friendly name for a household detail."""
    names = FIELD_NAMES.get(language) or FIELD_NAMES["en"]
    return names.get(field) or FIELD_NAMES["en"].get(field) or field.replace("_", " ").capitalize()
