"""
src/news/normalizers/geo.py — Geographic normalization utilities.

Validates country and language codes against ISO standards.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ISO 639-1 Language Codes
VALID_LANGUAGES: frozenset[str] = frozenset([
    "ab", "aa", "af", "ak", "sq", "am", "ar", "an", "hy", "as", "av", "ae",
    "ay", "az", "bm", "ba", "eu", "be", "bn", "bh", "bi", "bs", "br", "bg",
    "my", "ca", "ch", "ce", "ny", "zh", "cv", "kw", "co", "cr", "hr", "cs",
    "da", "dv", "nl", "dz", "en", "eo", "et", "ee", "fo", "fj", "fi", "fr",
    "ff", "gl", "ka", "de", "el", "gn", "gu", "ht", "ha", "he", "hz", "hi",
    "ho", "hu", "ia", "id", "ie", "ga", "ig", "ik", "io", "is", "it", "iu",
    "ja", "jv", "kl", "kn", "kr", "ks", "kk", "km", "ki", "rw", "ky", "kv",
    "kg", "ko", "ku", "kj", "la", "lb", "lg", "li", "ln", "lo", "lt", "lu",
    "lv", "gv", "mk", "mg", "ms", "ml", "mt", "mi", "mr", "mh", "mn", "na",
    "nv", "nd", "ne", "ng", "nb", "nn", "no", "ii", "nr", "oc", "oj", "cu",
    "om", "or", "os", "pa", "pi", "fa", "pl", "ps", "pt", "qu", "rm", "rn",
    "ro", "ru", "sa", "sc", "sd", "se", "sm", "sg", "sr", "gd", "sn", "si",
    "sk", "sl", "so", "st", "es", "su", "sw", "ss", "sv", "ta", "te", "tg",
    "th", "ti", "bo", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty",
    "ug", "uk", "ur", "uz", "ve", "vi", "vo", "wa", "cy", "wo", "fy", "xh",
    "yi", "yo", "za", "zu"
])

# ISO 3166-1 alpha-2 Country Codes
VALID_COUNTRIES: frozenset[str] = frozenset([
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
    "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
    "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
    "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK",
    "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR",
    "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS",
    "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
    "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM",
    "SN", "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF",
    "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW",
    "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW"
])


def normalize_language(code: str | None) -> str | None:
    """
    Normalize language code to lowercase ISO 639-1.
    Returns None if the code is invalid or missing.
    """
    if not code:
        return None
    
    normalized = code.strip().lower()
    
    # Handle cases like "en-US" -> "en"
    if "-" in normalized:
        normalized = normalized.split("-")[0]
        
    if normalized in VALID_LANGUAGES:
        return normalized
        
    log.debug("geo.py: invalid language code %r", code)
    return None


def normalize_country(code: str | None) -> str | None:
    """
    Normalize country code to uppercase ISO 3166-1 alpha-2.
    Returns None if the code is invalid or missing.
    """
    if not code:
        return None
        
    normalized = code.strip().upper()
    if normalized in VALID_COUNTRIES:
        return normalized
        
    log.debug("geo.py: invalid country code %r", code)
    return None


# ── Country / language NAMES → ISO codes ─────────────────────────────────────
# GDELT reports `sourcecountry` and NewsData reports `country` as English names, so a lookup table is the only safe way
# to get ISO alpha-2 (never truncate the string). Keys are casefolded; unknown names return None.
_COUNTRY_NAME_LINES = """
AF|afghanistan;AL|albania;DZ|algeria;AS|american samoa;AD|andorra;AO|angola;AI|anguilla;AG|antigua and barbuda;AR|argentina
AM|armenia;AW|aruba;AU|australia;AT|austria;AZ|azerbaijan;BS|bahamas;bahamas, the;BH|bahrain;BD|bangladesh;BB|barbados
BY|belarus;BE|belgium;BZ|belize;BJ|benin;BM|bermuda;BT|bhutan;BO|bolivia;BA|bosnia and herzegovina;bosnia-herzegovina;bosnia
BW|botswana;BR|brazil;BN|brunei;BG|bulgaria;BF|burkina faso;BI|burundi;KH|cambodia;CM|cameroon;CA|canada;CV|cape verde;cabo verde
KY|cayman islands;CF|central african republic;TD|chad;CL|chile;CN|china;CO|colombia;KM|comoros;CG|congo;republic of the congo
CD|democratic republic of the congo;congo, democratic republic of the;dr congo;drc;CR|costa rica;CI|ivory coast;cote d'ivoire;côte d'ivoire
HR|croatia;CU|cuba;CY|cyprus;CZ|czech republic;czechia;DK|denmark;DJ|djibouti;DM|dominica;DO|dominican republic;EC|ecuador
EG|egypt;SV|el salvador;GQ|equatorial guinea;ER|eritrea;EE|estonia;SZ|eswatini;swaziland;ET|ethiopia;FJ|fiji;FI|finland
FR|france;GF|french guiana;PF|french polynesia;GA|gabon;GM|gambia;gambia, the;GE|georgia;DE|germany;GH|ghana;GI|gibraltar
GR|greece;GL|greenland;GD|grenada;GP|guadeloupe;GU|guam;GT|guatemala;GN|guinea;GW|guinea-bissau;GY|guyana;HT|haiti
HN|honduras;HK|hong kong;HU|hungary;IS|iceland;IN|india;ID|indonesia;IR|iran;iran, islamic republic of;IQ|iraq;IE|ireland
IL|israel;IT|italy;JM|jamaica;JP|japan;JO|jordan;KZ|kazakhstan;KE|kenya;KI|kiribati;KP|north korea;korea, north
KR|south korea;korea, south;korea;KW|kuwait;KG|kyrgyzstan;LA|laos;LV|latvia;LB|lebanon;LS|lesotho;LR|liberia;LY|libya
LI|liechtenstein;LT|lithuania;LU|luxembourg;MO|macau;macao;MK|north macedonia;macedonia;MG|madagascar;MW|malawi;MY|malaysia
MV|maldives;ML|mali;MT|malta;MH|marshall islands;MQ|martinique;MR|mauritania;MU|mauritius;MX|mexico;FM|micronesia
MD|moldova;MC|monaco;MN|mongolia;ME|montenegro;MA|morocco;MZ|mozambique;MM|myanmar;burma;NA|namibia;NR|nauru;NP|nepal
NL|netherlands;the netherlands;holland;NC|new caledonia;NZ|new zealand;NI|nicaragua;NE|niger;NG|nigeria;NO|norway;OM|oman
PK|pakistan;PW|palau;PS|palestine;palestinian territory;west bank;gaza strip;PA|panama;PG|papua new guinea;PY|paraguay;PE|peru
PH|philippines;PL|poland;PT|portugal;PR|puerto rico;QA|qatar;RE|reunion;RO|romania;RU|russia;russian federation;RW|rwanda
KN|saint kitts and nevis;LC|saint lucia;VC|saint vincent and the grenadines;WS|samoa;SM|san marino;ST|sao tome and principe
SA|saudi arabia;SN|senegal;RS|serbia;SC|seychelles;SL|sierra leone;SG|singapore;SK|slovakia;SI|slovenia;SB|solomon islands
SO|somalia;ZA|south africa;SS|south sudan;ES|spain;LK|sri lanka;SD|sudan;SR|suriname;SE|sweden;CH|switzerland;SY|syria
TW|taiwan;TJ|tajikistan;TZ|tanzania;TH|thailand;TL|timor-leste;east timor;TG|togo;TO|tonga;TT|trinidad and tobago;TN|tunisia
TR|turkey;turkiye;türkiye;TM|turkmenistan;TV|tuvalu;UG|uganda;UA|ukraine;AE|united arab emirates;uae;GB|united kingdom;uk
great britain;britain;england;scotland;wales;northern ireland;US|united states;united states of america;usa;america;UY|uruguay
UZ|uzbekistan;VU|vanuatu;VA|vatican city;holy see;VE|venezuela;VN|vietnam;viet nam;YE|yemen;ZM|zambia;ZW|zimbabwe;FO|faroe islands;VG|british virgin islands;VI|us virgin islands;united states virgin islands;virgin islands;FK|falkland islands
TC|turks and caicos islands;EH|western sahara;IM|isle of man;JE|jersey;GG|guernsey;YT|mayotte;CK|cook islands;NU|niue
MP|northern mariana islands;MS|montserrat;SH|saint helena;PM|saint pierre and miquelon;WF|wallis and futuna;CW|curacao;curaçao
SX|sint maarten;BQ|bonaire;AX|aland islands;åland islands;CC|cocos islands;CX|christmas island;NF|norfolk island;TK|tokelau
SJ|svalbard;AQ|antarctica
"""


def _build_country_names() -> dict[str, str]:
    table: dict[str, str] = {}
    code = None
    for chunk in _COUNTRY_NAME_LINES.replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "|" in chunk:
            code, name = chunk.split("|", 1)
        else:
            name = chunk
        table[name.strip().casefold()] = code
    return table


COUNTRY_NAME_TO_ISO: dict[str, str] = _build_country_names()


def country_from_name(name: str | None) -> str | None:
    """English country name (GDELT / NewsData) -> ISO alpha-2, or None when unknown. Never guesses from a prefix."""
    if not name:
        return None
    return COUNTRY_NAME_TO_ISO.get(name.strip().casefold())


LANGUAGE_NAME_TO_ISO: dict[str, str] = {
    "english": "en", "hindi": "hi", "bengali": "bn", "tamil": "ta", "telugu": "te", "marathi": "mr", "gujarati": "gu",
    "kannada": "kn", "malayalam": "ml", "punjabi": "pa", "urdu": "ur", "spanish": "es", "french": "fr", "german": "de",
    "portuguese": "pt", "italian": "it", "russian": "ru", "arabic": "ar", "chinese": "zh", "japanese": "ja", "korean": "ko",
    "dutch": "nl", "turkish": "tr", "indonesian": "id", "thai": "th", "vietnamese": "vi", "polish": "pl", "ukrainian": "uk",
}


def language_from_provider(value: str | None) -> str | None:
    """Provider language ('en', 'English', 'english') -> ISO 639-1, or None when it cannot be interpreted."""
    if not value:
        return None
    key = value.strip().casefold()
    return LANGUAGE_NAME_TO_ISO.get(key) or normalize_language(key)
