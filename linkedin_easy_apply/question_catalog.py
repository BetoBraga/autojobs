from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class QuestionDefinition:
    key: str
    label: str
    category: str
    answer_type: str = "text"  # text | numeric | boolean | choice | multi_choice | date
    patterns: tuple[str, ...] = ()
    choices: tuple[str, ...] = ()
    dublin_recommended: bool = False
    social: bool = False
    help_text: str = ""


def _q(
    key: str,
    label: str,
    category: str,
    answer_type: str = "text",
    patterns: Iterable[str] = (),
    choices: Iterable[str] = (),
    *,
    dublin: bool = False,
    social: bool = False,
    help_text: str = "",
) -> QuestionDefinition:
    return QuestionDefinition(
        key=key,
        label=label,
        category=category,
        answer_type=answer_type,
        patterns=tuple(patterns),
        choices=tuple(choices),
        dublin_recommended=dublin,
        social=social,
        help_text=help_text,
    )


YES_NO = ("Yes", "No")
PREFER_NOT = ("Prefer not to say", "I prefer not to say", "Decline to self-identify")

# The list intentionally combines LinkedIn's documented screening-question families
# with common Easy Apply custom questions. Recruiters can still create arbitrary
# questions, so this catalog is complemented by semantic fallbacks in answer_engine.py.
QUESTION_CATALOG: tuple[QuestionDefinition, ...] = (
    # Ireland / Dublin work eligibility
    _q("ie_work_authorized", "Legally authorised to work in Ireland", "Ireland & work eligibility", "boolean",
       (r"legally authori[sz]ed to work (?:in )?ireland", r"right to work (?:in )?ireland", r"permission to work (?:in )?ireland", r"eligible to work (?:in )?ireland"), YES_NO, dublin=True,
       help_text="Answer based on your current legal right to work in Ireland."),
    _q("ie_sponsorship", "Require employment permit / visa sponsorship now or in future", "Ireland & work eligibility", "boolean",
       (r"require.*sponsor", r"sponsorship.*(?:visa|employment|work permit)", r"employment permit.*sponsor", r"visa sponsorship", r"work permit sponsorship"), YES_NO, dublin=True),
    _q("ie_current_permission", "Current Irish immigration / work permission", "Ireland & work eligibility", "choice",
       (r"(?:current|what).*immigration (?:status|permission)", r"irish (?:visa|stamp|permission|immigration status)", r"permission.*(?:stamp|ireland)"),
       ("Irish / EU / EEA / Swiss citizen", "Stamp 1", "Stamp 1G", "Stamp 2", "Stamp 3", "Stamp 4", "Stamp 4 EUFAM", "Employment Permit", "Other", "Prefer not to say"), dublin=True),
    _q("ie_stamp", "Irish immigration Stamp", "Ireland & work eligibility", "choice",
       (r"which (?:irish )?stamp", r"immigration stamp", r"stamp 1g", r"stamp 4"),
       ("Stamp 1", "Stamp 1G", "Stamp 2", "Stamp 3", "Stamp 4", "Stamp 4 EUFAM", "Not applicable", "Other"), dublin=True),
    _q("ie_employment_permit", "Irish employment permit type", "Ireland & work eligibility", "choice",
       (r"employment permit (?:type|status)", r"critical skills employment permit", r"general employment permit"),
       ("Critical Skills Employment Permit", "General Employment Permit", "Other employment permit", "Not required", "Not applicable"), dublin=True),
    _q("eu_eea_citizen", "EU / EEA / Swiss citizen", "Ireland & work eligibility", "boolean",
       (r"(?:eu|eea|european economic area|swiss).*(?:citizen|national)", r"citizen.*(?:eu|eea|switzerland)"), YES_NO, dublin=True),
    _q("irish_citizen", "Irish citizen", "Ireland & work eligibility", "boolean", (r"irish citizen", r"citizen of ireland"), YES_NO, dublin=True),
    _q("nationality", "Nationality / citizenship", "Ireland & work eligibility", "text", (r"^nationality$", r"citizenship", r"country of citizenship"), dublin=True),
    _q("passport_country", "Passport issuing country", "Ireland & work eligibility", "text", (r"passport.*(?:country|issued)",), dublin=True),
    _q("permit_expiry", "Work permission / permit expiry date", "Ireland & work eligibility", "date", (r"(?:permit|visa|permission|stamp).*(?:expir|valid until)",), dublin=True),

    # Location / Dublin working model
    _q("current_location", "Current city / location", "Availability & logistics", "text", (r"current (?:city|location|address)", r"where are you (?:currently )?(?:based|located)"), dublin=True),
    _q("dublin_based", "Currently based in Dublin", "Availability & logistics", "boolean", (r"(?:currently )?(?:based|located).*dublin", r"live.*dublin"), YES_NO, dublin=True),
    _q("commute_dublin", "Able to commute to Dublin", "Availability & logistics", "boolean", (r"commut.*dublin", r"travel.*dublin office", r"work.*dublin office"), YES_NO, dublin=True),
    _q("relocate_dublin", "Willing to relocate to Dublin / Ireland", "Availability & logistics", "boolean", (r"willing to relocate.*(?:dublin|ireland)", r"relocat.*(?:dublin|ireland)"), YES_NO, dublin=True),
    _q("relocation_needed", "Relocation assistance required", "Availability & logistics", "boolean", (r"relocation (?:assistance|support)", r"need.*relocat"), YES_NO, dublin=True),
    _q("hybrid_days", "Days per week available in office", "Availability & logistics", "numeric", (r"how many days.*(?:office|on.?site)", r"days per week.*(?:office|onsite|on-site|hybrid)"), dublin=True),
    _q("hybrid_ok", "Comfortable with hybrid working", "Availability & logistics", "boolean", (r"(?:comfortable|able|willing).*(?:hybrid|on.?site)", r"hybrid working"), YES_NO, dublin=True),
    _q("remote_ok", "Able to work remotely", "Availability & logistics", "boolean", (r"(?:able|willing).*(?:work )?remote", r"remote work"), YES_NO),
    _q("travel_percent", "Percentage willing to travel", "Availability & logistics", "numeric", (r"(?:percentage|percent|%).*(?:travel)", r"how much.*travel")),
    _q("travel_willing", "Willing to travel for work", "Availability & logistics", "boolean", (r"willing to travel", r"able to travel"), YES_NO),
    _q("driving_licence", "Valid driving licence", "Availability & logistics", "boolean", (r"driv(?:er|ing).*(?:licen[cs]e)", r"valid.*licen[cs]e"), YES_NO, dublin=True),
    _q("own_vehicle", "Access to own vehicle", "Availability & logistics", "boolean", (r"own (?:car|vehicle)", r"access to.*vehicle"), YES_NO),

    # Availability / contract
    _q("start_date", "Earliest start date", "Availability & logistics", "date", (r"(?:earliest|available).*start date", r"when can you start", r"start date"), dublin=True),
    _q("notice_period", "Notice period", "Availability & logistics", "text", (r"notice period", r"how much notice", r"current notice"), dublin=True),
    _q("available_immediately", "Available to start immediately", "Availability & logistics", "boolean", (r"available.*immediate", r"start immediately"), YES_NO),
    _q("full_time", "Available for full-time work", "Availability & logistics", "boolean", (r"available.*full.?time", r"work full.?time"), YES_NO),
    _q("part_time", "Available for part-time work", "Availability & logistics", "boolean", (r"available.*part.?time", r"work part.?time"), YES_NO),
    _q("contract_ok", "Open to contract work", "Availability & logistics", "boolean", (r"open to.*contract", r"contract (?:role|position)"), YES_NO),
    _q("shift_work", "Available for shift work", "Availability & logistics", "boolean", (r"shift work", r"work.*shifts", r"rotating shift"), YES_NO),
    _q("weekends", "Available to work weekends", "Availability & logistics", "boolean", (r"work.*weekends", r"weekend availability"), YES_NO),
    _q("evenings", "Available to work evenings / nights", "Availability & logistics", "boolean", (r"(?:evening|night).*(?:work|shift|availability)",), YES_NO),
    _q("overtime", "Available for overtime", "Availability & logistics", "boolean", (r"overtime",), YES_NO),
    _q("working_hours", "Preferred / available working hours", "Availability & logistics", "text", (r"working hours", r"hours.*available", r"availability.*hours")),

    # Compensation
    _q("salary_expectation", "Salary expectation", "Compensation", "numeric", (r"salary (?:expectation|expectations|requirement|requirements)", r"expected salary", r"desired salary", r"annual salary", r"base salary"), dublin=True),
    _q("salary_currency", "Salary currency", "Compensation", "choice", (r"salary currency", r"currency.*salary"), ("EUR", "GBP", "USD", "Other"), dublin=True),
    _q("salary_range", "Expected salary range", "Compensation", "text", (r"salary range", r"compensation range"), dublin=True),
    _q("hourly_rate", "Hourly / daily rate", "Compensation", "numeric", (r"hourly rate", r"daily rate", r"day rate", r"contract rate")),
    _q("current_salary", "Current salary / compensation", "Compensation", "numeric", (r"current salary", r"current compensation")),
    _q("compensation_flexible", "Compensation expectations flexible", "Compensation", "boolean", (r"compensation.*flexible", r"salary.*negotiable"), YES_NO),

    # Experience / expertise
    _q("years_total_experience", "Total years of professional experience", "Experience & skills", "numeric", (r"years.*(?:professional|total).*experience", r"total.*years.*experience"), dublin=True),
    _q("years_role_experience", "Years of relevant experience", "Experience & skills", "numeric", (r"how many years.*experience", r"years of (?:relevant|related).*experience", r"years.*working with"), dublin=True),
    _q("management_years", "Years of people-management experience", "Experience & skills", "numeric", (r"years.*(?:management|managing|people manager|leadership).*experience",)),
    _q("team_size", "Largest team managed", "Experience & skills", "numeric", (r"(?:team size|people).*(?:managed|led)", r"how many.*(?:managed|direct reports)")),
    _q("skill_proficiency", "Skill proficiency / expertise", "Experience & skills", "choice", (r"(?:skill )?proficiency.*(?:in|with)", r"level of expertise", r"skill level"), ("Beginner", "Intermediate", "Advanced", "Expert")),
    _q("specific_skill_years", "Years using a specific technology / skill", "Experience & skills", "numeric", (r"years.*(?:using|with|in).*(?:python|java|javascript|typescript|sql|aws|azure|gcp|kubernetes|docker|react|salesforce|sap|jira|linux|machine learning|data)",)),
    _q("industry_experience", "Industry experience", "Experience & skills", "boolean", (r"experience.*(?:industry|sector)", r"industry experience"), YES_NO),
    _q("leadership_experience", "Leadership experience", "Experience & skills", "boolean", (r"leadership experience", r"experience.*leading"), YES_NO),
    _q("customer_facing", "Customer-facing experience", "Experience & skills", "boolean", (r"customer.?facing", r"client.?facing"), YES_NO),
    _q("sales_experience", "Sales experience", "Experience & skills", "boolean", (r"sales experience",), YES_NO),
    _q("support_experience", "Technical / customer support experience", "Experience & skills", "boolean", (r"support experience", r"technical support"), YES_NO),
    _q("portfolio_url", "Portfolio URL", "Profile & contact", "text", (r"portfolio(?: url| link| website)?",)),
    _q("github_url", "GitHub profile URL", "Profile & contact", "text", (r"github(?: profile| url| link)?",)),
    _q("website_url", "Personal website", "Profile & contact", "text", (r"personal website", r"website url")),
    _q("linkedin_url", "LinkedIn profile URL", "Profile & contact", "text", (r"linkedin (?:profile|url|link)",)),

    # Education / certificates / languages
    _q("highest_education", "Highest level of education", "Education & credentials", "choice", (r"highest.*education", r"education level", r"highest degree"),
       ("Secondary school", "Certificate", "Diploma", "Bachelor's degree", "Master's degree", "Doctorate / PhD", "Other"), dublin=True),
    _q("degree_field", "Field of study / degree", "Education & credentials", "text", (r"field of study", r"degree.*(?:subject|discipline)", r"what.*degree")),
    _q("university", "University / institution", "Education & credentials", "text", (r"university", r"college", r"institution")),
    _q("graduation_year", "Graduation year", "Education & credentials", "numeric", (r"graduation year", r"year.*graduat")),
    _q("certification", "Required certification / licence", "Education & credentials", "boolean", (r"(?:have|hold|possess).*(?:certification|certificate|licen[cs]e|qualification)", r"certified.*"), YES_NO),
    _q("certification_name", "Certification / licence details", "Education & credentials", "text", (r"(?:certification|certificate|licen[cs]e).*(?:name|number|details)",)),
    _q("english_fluent", "Fluent / professional English", "Languages", "boolean", (r"(?:fluent|proficient).*(?:english)", r"english.*(?:fluency|proficiency)"), YES_NO, dublin=True),
    _q("english_level", "English proficiency level", "Languages", "choice", (r"english.*level", r"level.*english"), ("Basic", "Conversational", "Professional working", "Full professional", "Native / bilingual"), dublin=True),
    _q("irish_language", "Irish language proficiency", "Languages", "choice", (r"irish language", r"gaeilge"), ("None", "Basic", "Conversational", "Professional", "Fluent / native"), dublin=True),
    _q("language_other", "Other language proficiency", "Languages", "text", (r"(?:language|languages).*(?:speak|proficiency|fluent)",)),

    # Compliance / screening
    _q("background_check", "Willing / able to pass background check", "Compliance & screening", "boolean", (r"background check", r"background screening", r"vetting"), YES_NO),
    _q("garda_vetting", "Able / willing to complete Garda vetting", "Compliance & screening", "boolean", (r"garda vett", r"national vetting bureau"), YES_NO, dublin=True),
    _q("drug_test", "Willing to take drug test", "Compliance & screening", "boolean", (r"drug (?:test|screen)",), YES_NO),
    _q("reference_check", "Consent to reference checks", "Compliance & screening", "boolean", (r"reference check", r"contact.*references"), YES_NO),
    _q("non_compete", "Subject to non-compete / restrictive covenant", "Compliance & screening", "boolean", (r"non.?compete", r"restrictive covenant", r"contractual restriction"), YES_NO),
    _q("conflict_interest", "Potential conflict of interest", "Compliance & screening", "boolean", (r"conflict of interest",), YES_NO),
    _q("relative_employee", "Relative / close relation employed by company", "Compliance & screening", "boolean", (r"relative.*(?:employ|work).*company", r"family member.*company"), YES_NO),
    _q("previous_employee", "Previously employed by this company", "Compliance & screening", "boolean", (r"previously (?:worked|employed).*company", r"former employee"), YES_NO),
    _q("previous_applied", "Previously applied / interviewed here", "Compliance & screening", "boolean", (r"previously applied", r"previously interviewed"), YES_NO),
    _q("criminal_conviction", "Criminal conviction question", "Compliance & screening", "boolean", (r"criminal (?:conviction|record)", r"convicted of", r"criminal offence"), YES_NO, social=True),
    _q("security_clearance", "Security clearance", "Compliance & screening", "choice", (r"security clearance", r"clearance level"), ("None", "Eligible", "Current clearance", "Other")),
    _q("nda", "Willing to sign NDA / confidentiality agreement", "Compliance & screening", "boolean", (r"(?:nda|non.?disclosure|confidentiality agreement)",), YES_NO),

    # Motivation / free text
    _q("why_interested", "Why are you interested in this role?", "Motivation & free text", "text", (r"why.*(?:interested|apply|role|position|company)", r"what interests you")),
    _q("why_company", "Why do you want to work for this company?", "Motivation & free text", "text", (r"why.*(?:work|join).*(?:company|us|organisation|organization)",)),
    _q("why_fit", "Why are you a good fit?", "Motivation & free text", "text", (r"why.*(?:good fit|suitable|qualified)", r"what makes you.*fit")),
    _q("cover_note", "Cover note / additional information", "Motivation & free text", "text", (r"cover note", r"additional information", r"anything else", r"additional comments")),
    _q("achievement", "Relevant achievement / example", "Motivation & free text", "text", (r"describe.*(?:achievement|accomplishment|example|project)",)),
    _q("referral", "How did you hear about this role?", "Motivation & free text", "choice", (r"how did you hear", r"source.*(?:job|role|vacancy)"), ("LinkedIn", "Company website", "Recruiter", "Employee referral", "Job board", "Other")),
    _q("referred_by", "Employee referral name", "Motivation & free text", "text", (r"referred by", r"referral.*name", r"employee referral")),

    # Profile/contact
    _q("first_name", "First name", "Profile & contact", "text", (r"^first name$",)),
    _q("last_name", "Last name", "Profile & contact", "text", (r"^last name$", r"^surname$")),
    _q("preferred_name", "Preferred name", "Profile & contact", "text", (r"preferred name", r"known as")),
    _q("email", "Email address", "Profile & contact", "text", (r"email(?: address)?",)),
    _q("phone", "Phone number", "Profile & contact", "text", (r"phone(?: number)?", r"mobile(?: number)?"), dublin=True),
    _q("address", "Address", "Profile & contact", "text", (r"street address", r"home address", r"^address$")),
    _q("city", "City", "Profile & contact", "text", (r"^city$", r"town/city"), dublin=True),
    _q("county", "County", "Profile & contact", "text", (r"^county$", r"county of residence"), dublin=True),
    _q("postal_code", "Eircode / postal code", "Profile & contact", "text", (r"eircode", r"postal code", r"postcode", r"zip code"), dublin=True),
    _q("country", "Country of residence", "Profile & contact", "text", (r"country of residence", r"^country$"), dublin=True),
    _q("pronouns", "Pronouns", "Social & diversity", "choice", (r"pronouns",), ("he/him", "she/her", "they/them", "Other", "Prefer not to say"), social=True),

    # Social / diversity / equality monitoring. These are always opt-in values;
    # no sensitive answer is inferred from another field.
    _q("gender", "Gender", "Social & diversity", "choice", (r"^gender$", r"gender identity", r"how do you describe your gender"),
       ("Man", "Woman", "Non-binary", "Other", "Prefer not to say"), social=True),
    _q("sex", "Sex", "Social & diversity", "choice", (r"^sex$", r"sex assigned"), ("Male", "Female", "Intersex", "Prefer not to say"), social=True),
    _q("transgender", "Transgender identity", "Social & diversity", "choice", (r"transgender", r"trans status"), ("Yes", "No", "Prefer not to say"), social=True),
    _q("ethnicity", "Ethnic group / background", "Social & diversity", "choice", (r"ethnic(?:ity| group| background)", r"race/ethnicity", r"racial.*ethnic"),
       ("Irish", "Irish Traveller", "Roma", "Other White background", "African", "Other Black background", "Chinese", "Indian/Pakistani/Bangladeshi", "Other Asian background", "Arabic", "Mixed background", "Other", "Prefer not to say"), social=True, dublin=True),
    _q("race", "Race", "Social & diversity", "choice", (r"^race$", r"racial group"), ("White", "Black", "Asian", "Mixed", "Other", "Prefer not to say"), social=True),
    _q("disability", "Disability", "Social & diversity", "choice", (r"(?:have|having|consider yourself).*(?:disability|disabled)", r"disability status", r"^disability$"), ("Yes", "No", "Prefer not to say"), social=True, dublin=True),
    _q("reasonable_accommodation", "Need reasonable accommodation / workplace adjustment", "Social & diversity", "choice", (r"reasonable accommodation", r"workplace (?:adjustment|accommodation)", r"special accommodation"), ("Yes", "No", "Prefer not to say"), social=True, dublin=True),
    _q("veteran", "Veteran status", "Social & diversity", "choice", (r"veteran status", r"protected veteran", r"are you a veteran"), ("Yes", "No", "Prefer not to say", "Decline to self-identify"), social=True),
    _q("military_service", "Military / armed forces service", "Social & diversity", "choice", (r"military service", r"armed forces", r"served.*military", r"served.*army"), ("Yes", "No", "Prefer not to say"), social=True),
    _q("sexual_orientation", "Sexual orientation", "Social & diversity", "choice", (r"sexual orientation",), ("Heterosexual / straight", "Gay", "Lesbian", "Bisexual", "Other", "Prefer not to say"), social=True),
    _q("religion", "Religion / belief", "Social & diversity", "choice", (r"religion", r"religious belief",), ("No religion", "Roman Catholic", "Church of Ireland", "Islam", "Orthodox Christian", "Presbyterian", "Other", "Prefer not to say"), social=True, dublin=True),
    _q("civil_status", "Civil / marital status", "Social & diversity", "choice", (r"marital status", r"civil status"), ("Single", "Married", "Civil partnership", "Separated", "Divorced", "Widowed", "Other", "Prefer not to say"), social=True, dublin=True),
    _q("family_status", "Family / carer status", "Social & diversity", "choice", (r"family status", r"carer status", r"caregiver status", r"dependants"), ("Yes", "No", "Prefer not to say"), social=True, dublin=True),
    _q("traveller_community", "Member of the Traveller community", "Social & diversity", "choice", (r"traveller community", r"irish traveller"), ("Yes", "No", "Prefer not to say"), social=True, dublin=True),
    _q("roma_identity", "Roma identity", "Social & diversity", "choice", (r"roma (?:community|identity|background)",), ("Yes", "No", "Prefer not to say"), social=True, dublin=True),
    _q("age_band", "Age band", "Social & diversity", "choice", (r"age band", r"age range", r"age group"), ("Under 18", "18-24", "25-34", "35-44", "45-54", "55-64", "65+", "Prefer not to say"), social=True),
    _q("date_of_birth", "Date of birth", "Social & diversity", "date", (r"date of birth", r"birth date", r"dob"), social=True),
)

QUESTION_BY_KEY = {q.key: q for q in QUESTION_CATALOG}
CATEGORIES = tuple(dict.fromkeys(q.category for q in QUESTION_CATALOG))


def normalize_for_match(text: str) -> str:
    return " ".join(str(text).replace("\n", " ").strip().lower().split())


def match_question(question: str) -> QuestionDefinition | None:
    normalized = normalize_for_match(question)
    if not normalized:
        return None
    matches: list[tuple[int, QuestionDefinition]] = []
    numeric_cue = any(token in normalized for token in ("how many", "number of", "days per week", "years of", "percentage", "percent"))
    for definition in QUESTION_CATALOG:
        for pattern in definition.patterns:
            try:
                found = re.search(pattern, normalized, flags=re.IGNORECASE)
            except re.error:
                continue
            if not found:
                continue
            score = len(pattern) + len(found.group(0))
            if numeric_cue and definition.answer_type == "numeric":
                score += 60
            if "level" in normalized and definition.answer_type == "choice":
                score += 25
            if "dublin" in normalized and definition.dublin_recommended:
                score += 5
            matches.append((score, definition))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def is_social_question(question: str) -> bool:
    definition = match_question(question)
    if definition:
        return definition.social
    text = normalize_for_match(question)
    social_needles = (
        "gender", "sex", "ethnicity", "ethnic", "race", "racial", "disability", "disabled",
        "veteran", "military", "armed forces", "sexual orientation", "religion", "marital status",
        "civil status", "family status", "carer", "traveller", "roma", "pronoun", "date of birth",
        "age group", "age band", "transgender",
        "genero", "gênero", "sexo", "etnia", "raca", "raça", "deficiencia", "deficiência",
        "incapacidade", "veterano", "serviu", "servico militar", "serviço militar", "forcas armadas", "forças armadas",
        "orientacao sexual", "orientação sexual", "religiao", "religião", "estado civil", "pronome", "pronomes",
        "data de nascimento", "faixa etaria", "faixa etária", "transgenero", "transgênero",
    )
    return any(needle in text for needle in social_needles)
