# Testing Guide

This guide is for teammates who want to quickly test the demo and understand what behavior is expected.

## 1. Recommended sample CSV

Use a CSV like this for most tests:

```csv
employee_id,salary,age,height,weight,department
1001,85000,29,170,68,Sales
1002,90000,34,175,75,Finance
1003,95000,41,180,82,Engineering
1004,99000,38,178,79,Marketing
```

## 2. What to observe in each run

For every test, record:

- prompt
- whether `encrypt scalar` is checked
- success or failure
- error message, if any
- `Formula Path`
- `Encrypted Inputs`
- `Encrypted Constants`
- `Server View Formula`
- first 2-3 `Input / Expected / Decrypted` rows

## 3. Normal success tests

## Test A — natural-language multi-column formula

Prompt:

```text
Compute risk score salary * 3 + age
```

Expected:
- should succeed
- should use the validated formula path
- should encrypt 2 input columns

## Test B — single-column formula

Prompt:

```text
Compute score salary * 2 + 3
```

Expected:
- should succeed
- should still use the formula path
- single-column formula should not require planner fallback

## Test C — polynomial-style formula

Prompt:

```text
Use salary^2 + 5 * age + 6 as the risk score
```

Expected:
- should succeed
- should use validated formula path
- `pow` should work with constant exponent

## Test D — mean reduction

Prompt:

```text
Compute the mean of the salary column in this CSV.
```

Expected:
- should succeed
- should use reduction/planner path
- output preview input should look like a scalar summary such as column + row count

## Test E — sum reduction

Prompt:

```text
Sum all values in the age column.
```

Expected:
- should succeed
- should use reduction/planner path

## 4. Encrypt-scalar tests

Run these with `encrypt scalar` checked.

## Test F

Prompt:

```text
Compute score salary * 2 + 3
```

Expected:
- should succeed
- encrypted constants count should be greater than 0
- server view formula should hide eligible constants with `⟦c⟧`

## Test G

Prompt:

```text
Compute risk score salary * 3 + age
```

Expected:
- should succeed
- encrypted constants should include the scalar coefficient
- encrypted inputs should still be 2

## Test H

Prompt:

```text
Use salary^2 + 5 * age + 6 as the risk score
```

Expected:
- should succeed
- additive/multiplicative constants may be hidden as encrypted constants
- exponent should remain plaintext constant

## 5. Error-handling tests

These should be blocked on the trusted side before server compute.

## Error 1 — unknown column

Prompt:

```text
Compute score bonus * 3 + age
```

Expected:

```text
Formula references unknown CSV column 'bonus'.
```

## Error 2 — division unsupported

Prompt:

```text
Compute score salary / age
```

Expected:

```text
Unsupported formula syntax. Use only numeric columns, constants, +, -, *, and ^.
```

## Error 3 — comparison unsupported

Prompt:

```text
Compute score salary > age
```

Expected:

```text
Unsupported formula syntax. Use only numeric columns, constants, +, -, *, and ^.
```

## Error 4 — function call unsupported

Prompt:

```text
Compute score log(salary) + age
```

Expected:

```text
Unsupported formula syntax. Use only numeric columns, constants, +, -, *, and ^.
```

## Error 5 — no data provided

Prompt:

```text
Compute score salary * 2 + 3
```

Run with:
- no CSV upload
- no manual values
- no inline `data=[...]`

Expected frontend behavior:

```text
Please provide data: upload a CSV file, enter manual values, or include inline data in the prompt.
```

## 6. Malformed CSV tests

These should also be rejected before server compute.

## CSV Error A — missing numeric value

```csv
employee_id,salary,age,department
1001,85000,29,Sales
1002,,34,Finance
1003,95000,41,Engineering
```

Prompt:

```text
Compute score salary + age
```

## CSV Error B — non-numeric value

```csv
employee_id,salary,age,department
1001,85000,29,Sales
1002,not_a_number,34,Finance
1003,95000,41,Engineering
```

Prompt:

```text
Compute score salary + age
```

## CSV Error C — blank row

```csv
employee_id,salary,age,department
1001,85000,29,Sales

1002,90000,34,Finance
1003,95000,41,Engineering
```

## CSV Error D — mismatched row width

```csv
employee_id,salary,age,department
1001,85000,29,Sales
1002,90000,34
1003,95000,41,Engineering
```

## 7. Quick smoke-test matrix

If time is limited, run these 6 tests first:

1.
```text
Compute risk score salary * 3 + age
```

2.
```text
Compute score salary * 2 + 3
```

3.
```text
Compute the mean of the salary column in this CSV.
```

4.
```text
Compute score bonus * 3 + age
```

5.
```text
Compute score salary / age
```

6.
```text
Compute score log(salary) + age
```

## 8. Pass/fail checklist template

Use this template for team testing:

```text
Prompt:
Encrypt scalar checked:
CSV used:
Expected behavior:
Actual behavior:
Formula Path:
Encrypted Inputs:
Encrypted Constants:
Server View Formula:
Pass/Fail:
Notes:
```

## 9. Debugging hints

- Wrong prompt routing -> check `agent_side/input_data.py` and `agent_side/planner.py`
- Formula accepted when it should fail -> check `agent_side/formula_parser.py`
- Formula validated but server output wrong -> check `server_side/expression_eval.py` and `server_side/pipeline.py`
- UI displays strange result title or counts -> check `agent_side/app.py`, `agent_side/reporting.py`, and `server_side/app.py`
