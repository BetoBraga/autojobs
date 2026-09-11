# autojobs v2.6.0

## Language-agnostic autonomous Easy Apply

- Unicode-safe question normalization for CJK, Cyrillic, Arabic and other scripts.
- DOM field signatures persisted with Learned Answers for cross-language reuse.
- Answer resolution now prioritizes field structure (`type`, `inputmode`, `autocomplete`, stable names/data attributes) before language-specific wording.
- Factual profile autofill can be resolved from standard HTML autocomplete semantics such as email, telephone, name, address and country.
- Automatic mode adds a configurable `first_valid` fallback for otherwise unmappable dropdown/radio controls; every use is logged as an assumption.
- Required single checkboxes can use the same autonomous continuation policy in Automatic mode.
- Select placeholders with an empty first value are filtered without needing translated placeholder text.
- Easy Apply primary-action discovery has a structural fallback independent of the button label.
- A structurally closed Easy Apply dialog after a valid forward action can confirm submission without relying solely on localized success copy.
- Portable answer profiles now include learned field signatures and the autonomous choice strategy.

## Validation

- Added tests for Japanese, Cyrillic and Arabic question normalization.
- Added arbitrary-language email/numeric/choice resolution tests.
- Added cross-language Learned Answer reuse through structural boolean values.
- Added static checks for structural primary-action and field-signature wiring.
