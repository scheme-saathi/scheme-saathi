# Supporting document retention

Supporting documents are stored **without encryption** under
`data/private_documents/` by default. Set `SCHEME_SAATHI_DOCUMENT_STORE_DIR` to
choose a different local folder. Keep the folder private and do not upload
unredacted documents: mask Aadhaar, bank-account, and other ID numbers first.

Uploads expire after 30 days and can also be deleted from the confirmation
screen, when starting a new application, or when withdrawing consent.

An upload is also deleted with its application workflow when that workflow
expires (24 hours without use, or 7 days after it started) and by "Forget my
data", which removes every upload recorded for the household, from any session.
Uploads made before the household was recorded are found only through workflows
the server still knows; otherwise they expire after 30 days.
