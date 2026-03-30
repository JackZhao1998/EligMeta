def stable_disease_eligibility_mismatch(trial: list[dict], target: list[dict]) -> float:
    """Penalty function using LLM parser with comparison 'presence_match'."""
    import json
    trial_values = []
    attended_entities = ["diagnosis"]

    for entry in trial:
        if entry.get('Entity', '').lower() in attended_entities:
            text = json.dumps({k: entry.get(k, '') for k in ['Type', 'Attribute', 'Value', 'Condition', 'Sentence']})
            if text and text != 'NA':
                parsed = llm_parser(text, "Check if the patient has stable disease on the post-treatment scan at completion of first line platinum-containing therapy. Return 'Yes' or 'No' only. Do not explain your answer.")
                norm = str(parsed).lower().strip()
                try:
                    if 'presence_match' in ['greater_than', 'less_than']:
                        trial_values.append(float(norm))
                    elif norm.startswith('yes'):
                        trial_values.append(True)
                    elif norm.startswith('no'):
                        trial_values.append(False)
                    else:
                        trial_values.append(norm)
                except Exception:
                    continue

    target_val_raw = "Yes"
    target_val = str(target_val_raw).strip().lower()
    target_has_condition = True if target_val == 'yes' else False
    prior_has_condition = any(trial_values)
    if prior_has_condition != target_has_condition:
        return 0.8
    return 0.0