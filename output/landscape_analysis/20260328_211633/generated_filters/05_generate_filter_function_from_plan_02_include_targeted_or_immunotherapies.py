def include_targeted_or_immunotherapies(row):
    """Filter function using LLM parser with multiple comparisons and 'default' logic."""
    import json
    import re
    import ast
    # Combined logic: evaluate all conditions. Return True only if all pass.
    results = []

    # Condition 1: Extract and return the names of interventions that are classified as targeted therapies or immunotherapies. Return the names as a Python list or a single comma-separated string. Do not explain your answer. (presence_match targeted therapy or immunotherapy)
    fields_cond_0 = ["Interventions"]
    input_text_cond_0 = ' '.join([f"{f}: {row.get(f, '')}" for f in fields_cond_0])
    print(f'[LLM Input Condition 1] → {input_text_cond_0}')
    parsed_cond_0 = llm_parser(input_text_cond_0, 'Extract and return the names of interventions that are classified as targeted therapies or immunotherapies. Return the names as a Python list or a single comma-separated string. Do not explain your answer.').strip()
    print(f'[Parsed Condition 1] → {parsed_cond_0}')
    # Evaluate comparison 1
    result_cond_0 = parsed_cond_0.lower() == str("targeted therapy or immunotherapy").lower()
    results.append(result_cond_0)

    # Combine results
    return all(results)