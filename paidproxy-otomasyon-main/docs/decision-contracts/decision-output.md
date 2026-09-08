# Decision output contract

The schema standardizes the executable result. It does not constrain reasoning.

Required:

- `action`: research, sample, expand, full_scan, defer, drop, reassess, deep_test
- `resource_plan`
- `stop_condition`

A batch request must emit a decision item per candidate.
