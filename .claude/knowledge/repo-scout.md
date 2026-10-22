# repo-scout knowledge

Durable lessons for `repo-scout`. `/promote-memory` adds entries after user approval.

## Repository map (2026-10-22)

- All application code sits at the repository root. There is no package folder yet.
- `app.py`: Streamlit entry point. Owner: `streamlit-ui-builder`.
- `auth_utils.py`: database connection, bcrypt auth and recommendation queries. Auth functions belong to `streamlit-ui-builder`; query functions belong to `ml-data-pipeline`.
- No Siamese network, BERT, ingestion, migration or test code exists in the repository. Recommendations come precomputed from the `siamese_recommendations` table.
- `Cross_Domain_Rec_AI-main.zip` is an untracked copy of the root files. Ignore it.
