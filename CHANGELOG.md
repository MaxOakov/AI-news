# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Inline keyboard buttons for `/gemini_version` command to allow users to select Gemini model directly from Telegram
- `update_gemini_model_in_env()` function to dynamically update `.env` file with selected model
- `set_model_callback()` handler to process model selection from inline buttons
- Support for two Gemini models:
  - `gemini-2.5-flash`
  - `gemini-3.1-flash-preview`
- Automatic `.env` creation if it doesn't exist
- Runtime model configuration updates in `os.environ` and `config.GEMINI_MODEL`

### Changed
- `/gemini_version` command now displays interactive buttons instead of text instructions
- Refactored bot command handlers to use `CallbackQueryHandler` for button interactions
- Updated imports to include `InlineKeyboardButton`, `InlineKeyboardMarkup`, and `CallbackQueryHandler`

### Improved
- User experience: Users can now select model directly from chat instead of manual `.env` editing
- Error handling: `.env` file updates are wrapped in try-except with user feedback
- Message feedback: Bot confirms model update with edit message instead of sending new message

### Technical Details
- Added `CallbackQueryHandler` with pattern `^set_model:` to route button callbacks
- Implemented safe file I/O with UTF-8 encoding and graceful error handling
- Model selection data encoded in callback_data as `set_model:<model_name>`
