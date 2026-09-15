# AI Tool Discovery & Risk Classification

**Company / Org:** Cyera  
**Challenge Advisor:** Shubham Arya, sa2382@cornell.edu   
**AI Coach:** Aram Ramos, aram.ramos@breakthroughtech.com  
**Program:** Break Through Tech AI Studio - Fall 2026  

---

## 🏢 About Cyera
Cyera operates in the data security and governance industry, focusing on providing comprehensive visibility and control over an organization's data landscape. Their team aims to help companies address critical challenges related to data security, compliance, and risk management in the modern enterprise.

---

## 🎯 The Challenge
### Project Summary
In this project, you will use enterprise SaaS metadata, browser/network activity logs, employee application usage data, and publicly available AI tool datasets along with NLP, embeddings, clustering, classification models, and LLM-based reasoning techniques to build a system that automatically discovers AI tools used across an organization, classifies their business purpose and risk level, and generates governance insights. This will help our company address the growing challenge of shadow AI adoption, compliance risk, data leakage exposure, and lack of visibility into enterprise AI usage.

### Success Criteria
Success for this project will be measured through a combination of machine learning performance, system usability, and business impact simulation.

Model Performance Metrics   
- Accuracy, precision, recall, and F1 score for identifying whether a tool is AI related
- Multi class classification accuracy for categorizing AI tools into business function categories such as coding assistants, content generation, analytics, or customer support
- Evaluation of risk scoring consistency against predefined governance criteria
- Semantic retrieval relevance for the RAG assistant using similarity scoring and response quality evaluation
- System Functionality Metrics
- Ability to successfully ingest and process synthetic enterprise activity data
- Ability to detect and classify previously unseen AI tools using embeddings and semantic similarity
- Response quality and usefulness of the conversational governance assistant
- Dashboard functionality including filtering, risk visualization, and trend reporting
- User Experience & Business Value

A successful outcome by December would include:   
- A working prototype that provides visibility into enterprise AI tool usage
- Automated identification of potentially high risk or unapproved AI tools
- Actionable governance insights and summaries generated through natural language interaction
- Demonstrated reduction in manual effort required to review and categorize AI tools
- Clear visualizations showing AI adoption trends across departments or business functions

Final Deliverables   

_By the end of the program, the team should deliver:_

- A trained ML classification pipeline
- A governance risk scoring engine
- A RAG based conversational assistant
- A lightweight dashboard or web application
- Technical documentation and a final presentation demonstrating real world applicability of the solution

A highly successful project would demonstrate that the system can accurately classify AI tools, identify governance concerns, and provide meaningful insights that could realistically support enterprise AI governance workflows.


### Project Milestones
Use these milestones to guide your work. Your team will create a GitHub Projects board to track tasks within each milestone.
| Month | Milestone | Key Activities |
|---|---|---|
| September | Problem Definition, Research, and Data Preparation | • Define the business problem around enterprise AI tool visibility and governance<br>• Research existing AI governance and shadow AI management approaches<br>• Identify project scope, user personas, and success metrics<br>• Collect and clean publicly available AI tool datasets and SaaS metadata<br>• Generate synthetic enterprise usage data such as browser logs, application usage records, and department level activity<br>• Perform exploratory data analysis and visualize usage patterns<br>• Define AI tool categories and governance risk criteria<br>• Build initial baseline models for AI tool detection and categorization |
| October | Model Development and Intelligence Layer | • Improve and optimize AI tool classification models using NLP and embeddings<br>• Develop the governance risk scoring engine<br>• Build semantic search and vector retrieval pipeline<br>• Implement a RAG based conversational assistant for governance queries<br>• Test different prompts and evaluate response quality<br>• Develop APIs or backend workflows connecting models and datasets<br>• Begin frontend/dashboard development for displaying governance insights<br>• Conduct intermediate testing and model evaluation |
| November | Integration, Evaluation, and Final Demo | • Integrate all components into a unified application<br>• Finalize dashboard visualizations and conversational assistant experience<br>• Add governance insight summaries and reporting features<br>• Evaluate model accuracy, retrieval quality, and usability<br>• Conduct fairness and bias analysis where applicable<br>• Optimize performance and improve user experience<br>• Prepare final presentation, technical documentation, and live demo<br>• Deliver a working prototype showcasing AI tool discovery, categorization, and governance insights |

> **Note for the team:** Please create a GitHub Projects board in this repository to break these milestones into weekly tasks. Go to the **Projects** tab → **New project** → Choose **Board** → Add columns for each month.

---

## 📊 Dataset
**Name and Source:** AIToolBuzz.com 16K AI Tools Database (Kaggle)   
**Format:** CSV/JSON   
**Size:** Under 1GB   
**Location:** https://www.kaggle.com/datasets/devadigax/aitoolbuzz-com-16k-ai-tools-database

### Key Details
- Contains approximately 16,000 AI tool listings with fields such as tool name, description, category, use case tags, pricing model, and launch date
- Known limitations: categories may be inconsistent or overlapping across entries; descriptions vary in length and quality; some tools may be deprecated or no longer active -- clean and deduplicate before modeling
- In addition to this dataset, your team will generate synthetic enterprise usage data (browser/network logs, app usage records, department-level activity) to simulate real-world shadow AI discovery scenarios
- No formal data dictionary is provided; perform your own EDA to understand field distributions and quality before modeling

---

## 🛠️ Suggested Approach

**ML Problem Type:** Classification, Clustering, NLP,Deep Learning / Neural Networks, LLMs/ Generative AI, Transfer Learning / Pre-trained Models

**Recommended Libraries:**
- `pandas`, `numpy` -- data loading, cleaning, and manipulation
- `scikit-learn` -- classification models, clustering, preprocessing, and evaluation
- `sentence-transformers` -- text embeddings for semantic similarity and unseen tool detection
- `transformers` (Hugging Face) -- pre-trained NLP models for text classification
- `faiss-cpu` or `chromadb` -- vector store for the RAG retrieval pipeline
- `langchain` or `llama-index` -- RAG pipeline orchestration and LLM integration
- `openai` or `anthropic` -- LLM API for the conversational governance assistant
- `streamlit` or `plotly` / `dash` -- lightweight dashboard and visualizations
- `matplotlib`, `seaborn` -- EDA and result visualizations
- `nltk` or `spacy` -- text preprocessing (tokenization, stopword removal, etc.)

**Evaluation Metrics:**
- Binary AI tool detection: Accuracy, Precision, Recall, F1 score
- Multi-class business function categorization: Macro F1, per-class Precision and Recall, Confusion Matrix
- Clustering quality: Silhouette score
- RAG retrieval: Cosine similarity between query and retrieved chunks, response quality via human review
- Risk scoring: Consistency score against predefined governance rubric

---

## 📚 Resources to Get Started

The following resources will help your team understand the problem space and potential technical approaches for this project:

**Background Reading:**
- [Gartner: Managing the Risks of Shadow AI](https://www.gartner.com/en/articles/the-rise-of-shadow-ai) -- overview of shadow AI risk in enterprises
- [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/) -- foundational reading on AI security and governance risks
- [McKinsey: The State of AI in 2024](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai) -- industry context on enterprise AI adoption trends

**Technical Tutorials:**
- [Hugging Face Text Classification Tutorial](https://huggingface.co/docs/transformers/tasks/sequence_classification) -- how to fine-tune a pre-trained model for classification
- [Sentence Transformers Quickstart](https://www.sbert.net/docs/quickstart.html) -- building semantic similarity and embedding pipelines
- [LangChain RAG Tutorial](https://python.langchain.com/docs/tutorials/rag/) -- building a retrieval-augmented generation pipeline end to end
- [Scikit-learn User Guide](https://scikit-learn.org/stable/user_guide.html) -- reference for all classical ML models and evaluation tools

**Code Examples:**
- [Hugging Face Text Classification Examples](https://github.com/huggingface/transformers/tree/main/examples/pytorch/text-classification) -- starter code for NLP classification
- [LangChain RAG Quickstart Notebook](https://github.com/langchain-ai/langchain/blob/master/docs/docs/tutorials/rag.ipynb) -- end-to-end RAG implementation reference
- [Streamlit Gallery](https://streamlit.io/gallery) -- dashboard examples built with Streamlit

**Other:**
- [fast.ai Practical Deep Learning for Coders](https://course.fast.ai/) -- free course covering NLP, classification, and model deployment
- [Kaggle Learn: Intro to NLP](https://www.kaggle.com/learn/natural-language-processing) -- short free course on NLP fundamentals

*Feel free to explore beyond these, and share anything interesting you find with me!*

---

## 🤝 How We'll Work Together

**Official check-ins:** During our biweekly 45-minute AI Studio Lab Section meeting block (2nd and 4th week of every month)

 **Other ways to reach out to me with questions:** 
* Email: sa2382@cornell.edu -- please copy your teammates and AI Coach Aram on all emails
* Break Through Tech Discord: reach out in your team channel; I will aim to respond within 48 hours
* For urgent questions, contact your AI Studio Coach Aram Ramos first
* To request an additional check-in outside the biweekly sessions, email me with at least 48 hours notice

**Recommended free coding / collaboration tools**
* [Google Colab](https://colab.research.google.com/) -- free GPU-backed Jupyter notebooks, no local setup required
* [GitHub Projects](https://github.com/features/project-management) -- task tracking board for this repo (see the Projects tab)
* [Weights & Biases free tier](https://wandb.ai/) -- experiment tracking and model visualization
* [Hugging Face free tier](https://huggingface.co/) -- model hosting, datasets, and Spaces for demos

---

## 🚀 Getting Started

1. **Review this overview document** and note any questions for our first meeting
2. **Begin reviewing the dataset** using the link above
3. **Read the GitHub Projects documentation** [here](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects)

I’m excited to work with you!

---

## ❓ Questions?

Please bring any questions to our first meeting during the week of August 24th (Break Through Tech’s Bridge to Studio - Session C).
