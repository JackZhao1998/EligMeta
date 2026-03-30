def include_survival_outcomes(row):
    """Filter function using LLM parser with multiple comparisons and 'default' logic."""
    import json
    import re
    import ast
    # Combined logic: evaluate all conditions. Return True only if all pass.
    results = []

    # Condition 1: Identify if the trial reports survival outcomes such as progression-free survival (PFS) or overall survival (OS). Return 'Yes' if such outcomes are reported, otherwise return 'No'. Do not explain your answer. (equal_to Yes)
    fields_cond_0 = ["Primary Outcome", "Secondary Outcome", "Summary"]
    input_text_cond_0 = ' '.join([f"{f}: {row.get(f, '')}" for f in fields_cond_0])
    print('[LLM Input Condition 1] -> ' + input_text_cond_0.encode('ascii', errors='replace').decode('ascii'))
    parsed_cond_0 = llm_parser(input_text_cond_0, "Identify if the trial reports survival outcomes such as progression-free survival (PFS) or overall survival (OS). Return 'Yes' if such outcomes are reported, otherwise return 'No'. Do not explain your answer.").strip()
    print('[Parsed Condition 1] -> ' + parsed_cond_0.encode('ascii', errors='replace').decode('ascii'))
    # Evaluate comparison 1
    result_cond_0 = parsed_cond_0.lower() == str("Yes").lower()
    results.append(result_cond_0)

    # Combine results
    return all(results)