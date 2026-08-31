# Introduction role-name fix

Updated only the student year-role mapping in `cogs/introduction.py`.

The `/setup` form still accepts:
- 1st Year
- 2nd Year
- 3rd Year
- 4th Year

The bot now maps both DAT and GD to these Discord role names:

- DAT-1st-Year
- DAT-2nd-Year
- DAT-3rd-Year
- DAT-4th-Year
- GD-1st-Year
- GD-2nd-Year
- GD-3rd-Year
- GD-4th-Year

No other onboarding logic was changed.
