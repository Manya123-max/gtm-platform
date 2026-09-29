def clean_company_name(name) -> str:
    if not name:
        return ""
    import re
    # Remove parenthetical details
    name = re.sub(r"\(.*?\)", "", name)
    # Remove suffixes after common delimiters with surrounding spaces or specific characters, but NOT raw hyphens inside words
    for delimiter in [" | ", " - ", " — ", " , "]:
        if delimiter in name:
            name = name.split(delimiter)[0]
    
    if ", " in name:
        name = name.split(", ")[0]
        
    suffixes = [
        "corporation", "corp.", "corp", 
        "incorporated", "inc.", "inc", 
        "limited", "ltd.", "ltd", 
        "llc", "l.l.c.", 
        "association", "assn.",
        "worldwide", "holdings", "group",
        "technologies", "technology", "tech",
        "services", "systems", "solutions",
        "mena", "europe", "international", "intl."
    ]
    
    name_lower = name.lower().strip()
    # Clean multiple suffixes iteratively
    cleaned = True
    while cleaned:
        cleaned = False
        for suffix in suffixes:
            # Check both space and hyphen prefixes
            for sep in [" ", "-"]:
                full_suffix = sep + suffix
                if name_lower.endswith(full_suffix):
                    remaining_len = len(name_lower) - len(full_suffix)
                    if remaining_len >= 3:
                        name = name[:remaining_len].strip()
                        name_lower = name.lower().strip()
                        cleaned = True
                        break
            if cleaned:
                break
                    
    return name.strip()

test_names = [
    "Galvin Technologies",
    "EI-Technologies MENA",
    "AvSight",
    "Lumary",
    "TLA-LLC",
    "Hello Better",
    "GrowthOps",
    "ScalePath",
    "RevStack AI",
    "DataBridge",
    "PipelineCo",
    "SalesForge"
]

for name in test_names:
    print(f"'{name}' -> '{clean_company_name(name)}'")
