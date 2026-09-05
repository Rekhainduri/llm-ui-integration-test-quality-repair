\# Test Generation Protocol



\## 1. Target Applications



The final generation protocol used four web applications:



\- BookStore

\- JPetStore 6

\- Spring PetClinic

\- HelpDeskApp



The workflow set contained 140 predefined workflows across the four applications.



\## 2. LLM Families



Integration tests were generated using:



\- OpenAI

\- DeepSeek

\- Claude



\## 3. Prompt Strategies



Three prompt strategies were used:



\- P1: Zero-shot test generation based on the workflow requirement.

\- P2: Project-aware generation using workflow and target-application information.

\- P3: Project-aware generation with additional expected-oracle information.



\## 4. Generation Variants



For each applicable model–prompt–workflow combination, independent generation variants were produced:



\- V1

\- V2

\- V3



The variants represent separate generations rather than manually modified copies.



\## 5. Final Protocol-Aligned Corpus



Only records conforming to the final generation protocol were retained for the primary RQ1/RQ2 analysis.



\- Total records: 2,783

\- Successful execution outcomes: 303

\- Failure outcomes: 2,480



Historical or out-of-protocol records were retained only for audit purposes and were excluded from the final protocol-aligned analysis.

