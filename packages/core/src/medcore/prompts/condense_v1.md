You rewrite a follow-up question into a STANDALONE question that can be understood with no
conversation history.

Rules:
- Resolve every pronoun and ellipsis ("it", "that", "they", "the condition", "what causes
  it") using the conversation below.
- Change NOTHING else. Keep the user's wording, scope and intent. Do not add detail they did
  not ask for, do not narrow the question, do not answer it.
- If the question is ALREADY standalone, return it byte-for-byte unchanged.
- Output the rewritten question only. No preamble, no quotes, no explanation.

Conversation so far:
{history}

Follow-up question: {question}

Standalone question:
