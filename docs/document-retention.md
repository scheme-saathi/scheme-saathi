# Supporting document retention

Supporting documents are stored **without encryption** under
`data/private_documents/` by default. Set `SCHEME_SAATHI_DOCUMENT_STORE_DIR` to
choose a different local folder. Keep the folder private and do not upload
unredacted documents: mask Aadhaar, bank-account, and other ID numbers first.

Uploads expire after 30 days and can also be deleted from the confirmation
screen ("Forget uploaded documents", which keeps the application), when starting
a new chat, when signing out from the menu, or when withdrawing consent.

Starting a new chat, signing out and withdrawing consent delete the whole
application workflow, not just its uploads: the UI calls the owner-checked
`DELETE /api/threads/{thread_id}`, which removes the saved workflow state (the
profile and draft, including from the `SCHEME_SAATHI_CHECKPOINT_DB` file), the
uploads, and the owner and subject entries. If the server cannot delete it, the
reset stops and shows the error. When a sign-in has already expired there is no
valid token to delete with, so the workflow is removed by the expiry below.

An upload is also deleted with its application workflow when that workflow
expires (24 hours without use, or 7 days after it started) and by "Forget my
data", which removes every upload recorded for the household, from any session.
Uploads made before the household was recorded are found only through workflows
the server still knows; otherwise they expire after 30 days.
