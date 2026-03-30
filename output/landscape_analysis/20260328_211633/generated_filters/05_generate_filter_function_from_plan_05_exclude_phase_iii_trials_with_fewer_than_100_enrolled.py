def exclude_phase_iii_trials_with_fewer_than_100_enrolled(row):
    """Filter function using LLM parser with multiple comparisons and 'sequential' logic."""
    import json
    import re
    import ast
    # Sequential logic: exactly two conditions (gatekeeper + exclusion logic).

    # Condition 1: Check if the trial is in Phase III. Return 'Yes' if it is Phase III, otherwise return 'No'. Do not explain your answer. (equal_to Yes)
    fields_cond_0 = ["Phase"]
    input_text_cond_0 = ' '.join([f"{f}: {row.get(f, '')}" for f in fields_cond_0])
    print(f'[LLM Input Condition 1] → {input_text_cond_0}')
    parsed_cond_0 = llm_parser(input_text_cond_0, "Check if the trial is in Phase III. Return 'Yes' if it is Phase III, otherwise return 'No'. Do not explain your answer.").strip()
    print(f'[Parsed Condition 1] → {parsed_cond_0}')
    # Evaluate comparison 1
    result_cond_0 = parsed_cond_0.lower() == str("Yes").lower()

    # Condition 2: Extract the number of enrolled patients. Return a number only. Do not include units or explanations. (greater_than 100)
    fields_cond_1 = ["Enrollment"]
    input_text_cond_1 = ' '.join([f"{f}: {row.get(f, '')}" for f in fields_cond_1])
    print(f'[LLM Input Condition 2] → {input_text_cond_1}')
    parsed_cond_1 = llm_parser(input_text_cond_1, 'Extract the number of enrolled patients. Return a number only. Do not include units or explanations.').strip()
    print(f'[Parsed Condition 2] → {parsed_cond_1}')
    # Evaluate comparison 2
    try:
        val_cond_1 = float(parsed_cond_1)
        result_cond_1 = val_cond_1 > 100
    except:
        result_cond_1 = False
    # If gatekeeper fails, keep row
    if not result_cond_0:
        return True
    # If exclusion logic fails, filter out
    if not result_cond_1:
        return False
    # Both pass, keep row
    return True