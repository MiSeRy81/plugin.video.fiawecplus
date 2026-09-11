# Contributing to FIAWEC+

Contributions and focused pull requests are welcome.

## Before opening a pull request

- Keep the change limited to one feature, fix or refactor where possible.
- Do not commit credentials, cookies, access tokens, refresh tokens or personal Kodi data.
- Make sure all modified Python files compile with Python 3.
- Test the affected navigation path in Kodi.
- If playback is affected, test at least one freely accessible item where possible.
- If event matching is affected, test across WEC, ELMS and MLMC and check similarly named events such as Le Mans and Lone Star Le Mans.

## Source structure

Kodi starts the add-on through `main.py`. Shared responsibilities are kept in `resources/lib/`. Please place new logic in the most appropriate existing module rather than growing `main.py` unnecessarily.

## Pull request description

Please include:

- what changed;
- why the change is needed;
- what you tested;
- Kodi version and platform used for testing.
