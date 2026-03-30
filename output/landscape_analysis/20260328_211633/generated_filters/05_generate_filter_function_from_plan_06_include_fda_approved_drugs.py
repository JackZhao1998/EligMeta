def include_fda_approved_drugs(row):
    """Filter function using LLM parser with multiple comparisons and 'default' logic."""
    import json
    import re
    import ast
    # Combined logic: evaluate all conditions. Return True only if all pass.
    results = []

    # Condition 1: Extract and return only the drug or intervention names under investigation as a Python list or a single comma-separated string. Do not perform any membership check. (in_list None)
    fields_cond_0 = ["Interventions"]
    input_text_cond_0 = ' '.join([f"{f}: {row.get(f, '')}" for f in fields_cond_0])
    print(f'[LLM Input Condition 1] → {input_text_cond_0}')
    parsed_cond_0 = llm_parser(input_text_cond_0, 'Extract and return only the drug or intervention names under investigation as a Python list or a single comma-separated string. Do not perform any membership check.').strip()
    print(f'[Parsed Condition 1] → {parsed_cond_0}')
    # Evaluate comparison 1
    # Membership check for ONLY the first extracted item (robust to list or delimited string)
    membership_list = set(FDA_approved_drugs_gastric)
    try:
        items = ast.literal_eval(parsed_cond_0)
        if isinstance(items, list):
            first_item = str(items[0]).strip().lower() if items else ''
        else:
            raise ValueError
    except Exception:
        all_items = [item.strip().lower() for item in re.split(r'[,\n;]+', parsed_cond_0) if item.strip().lower() != 'none']
        first_item = all_items[0] if all_items else ''
    fda_names = [m.lower() for m in membership_list]
    result_cond_0 = any(first_item in fda or fda in first_item for fda in fda_names) if first_item else False
    results.append(result_cond_0)

    # Combine results
    return all(results)