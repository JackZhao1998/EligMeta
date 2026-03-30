def check_treatment_duration(trial: list[dict], target: list[dict]) -> float:
    """Penalty function using LLM parser with comparison 'greater_than'."""
    import json
    trial_values = []
    attended_entities = ["previous treatment"]

    for entry in trial:
        if entry.get('Entity', '').lower() in attended_entities:
            text = json.dumps({k: entry.get(k, '') for k in ['Type', 'Attribute', 'Value', 'Condition', 'Sentence']})
            if text and text != 'NA':
                parsed = llm_parser(text, 'Extract the number of weeks of continuous platinum treatment without progression. Return a number only. Do not include units or explanations.')
                norm = str(parsed).lower().strip()
                try:
                    if 'greater_than' in ['greater_than', 'less_than']:
                        trial_values.append(float(norm))
                    elif norm.startswith('yes'):
                        trial_values.append(True)
                    elif norm.startswith('no'):
                        trial_values.append(False)
                    else:
                        trial_values.append(norm)
                except Exception:
                    continue

    if not trial_values:
        return 0.0
    target_val = 16
    if 'greater_than' in ['greater_than', 'less_than']:
        try:
            target_val = float(target_val)
        except Exception:
            return 0.0
    for trial_val in trial_values:
        if trial_val > target_val:
            return 0.7
    return 0.0