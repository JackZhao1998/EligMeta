def include_gastric_or_gastroesophageal_junction_cancer(row):
    """Filter function using LLM parser with multiple comparisons and 'default' logic."""
    import json
    import re
    import ast
    # Combined logic: evaluate all conditions. Return True only if all pass.
    results = []

    # Condition 1: Identify if the trial studies gastric cancer or gastroesophageal junction cancer. Return 'Yes' if either condition is studied, otherwise return 'No'. Do not explain your answer. (equal_to Yes)
    fields_cond_0 = ["Conditions", "Summary", "Eligibility"]
    input_text_cond_0 = ' '.join([f"{f}: {row.get(f, '')}" for f in fields_cond_0])
    print(f'[LLM Input Condition 1] → {input_text_cond_0}')
    parsed_cond_0 = llm_parser(input_text_cond_0, "Identify if the trial studies gastric cancer or gastroesophageal junction cancer. Return 'Yes' if either condition is studied, otherwise return 'No'. Do not explain your answer.").strip()
    print(f'[Parsed Condition 1] → {parsed_cond_0}')
    # Evaluate comparison 1
    result_cond_0 = parsed_cond_0.lower() == str("Yes").lower()
    results.append(result_cond_0)

    # Combine results
    return all(results)