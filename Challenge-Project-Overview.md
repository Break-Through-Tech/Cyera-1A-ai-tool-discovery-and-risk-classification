---

> ## Challenge Advisor: Update & Finalize Your Project Overview
>
> > 💡 **These grey text instructions are just for you, the team's Challenge Advisor; please delete them once you have completed the steps below.**
>
> We've pre-populated this Challenge Project Overview page — which is what will be shared with your Break Through Tech student team in August — using the details from your submission form. You should have received an email inviting you to join this repo as a Collaborator, enabling you to add files and make edits.
> 
> In order for your project to be finalized and assigned to a team, please:
> 1. **Review all sections below** and update or expand any content as needed, making sure to address the SME Feedback in the section immediately below. Look for square brackets to find the places below that require additional inputs from you (e.g., "About [Company / Org Name]").
> 2. **Add your dataset** to the [data folder](data) in this repo.
> 3. **Close the Issue assigned to you in this repo** to let us know that you have made your edits and the overview page is ready for final review. You can do this by going to the _Issues_ tab in the top left section of the menu above, add a comment that says "CA review complete", and click the button to Close the Issue. 
>
> If you're unfamiliar with how to edit a page like this in GitHub, check out [this tutorial](https://ubc-lib-geo.github.io/gis-workshop-waml-template/content/handson/edit-readme.html) for a quick overview (start with step 2 and only edit this page), and [this guide](https://ubc-lib-geo.github.io/gis-workshop-waml-template/content/markdown.html) on how to use Markdown to compose text.
>
>
> ❌ Remember that this is a public repo. Do NOT include: Proprietary data, PII, API keys, credentials, or anything confidential.

---

## 📋 BTT Internal Evaluation Notes
*(This section is for BTT staff and CAs only — remove before sharing with students)*

### Technical Vetting
| Check | Status | Notes |
| :--- | :--- | :--- |
| Python Compatibility | 🟢 | The tech stack is primarily centered on Python and leverages well-known libraries for ML and NLP tasks, aligning with the students' ML Foundations experience. |
| Data Readiness | 🟢 | Data is readily available and under 1GB, minimizing potential cleaning overhead. It consists of publicly available datasets and enterprise logs that can be ingested with minimal preprocessing. |
| Resource Check | 🟢 | Using free-tier tools like Google Colab ensures accessibility without relying on specialized hardware or proprietary software. |

### Internal Scores
- **Student Fit Score:** 8/10
- **Technical Depth Score:** 7/10
- **Overall Recommendation:** APPROVE

### Advisor Feedback Draft
This project presents a solid foundation with a clear application in a relevant area of concern for organizations. However, I recommend focusing on integrating disparate datasets for more hands-on learning. Additionally, prioritize a guided approach for the NLP aspect to ensure students engage deeply without becoming overwhelmed. Encourage awareness of a well-structured timeline to keep the team aligned on deliverables.

---

# AI Tool Discovery & Risk Classification

**Company / Org:** Cyera  
**Challenge Advisor:** Shubham Arya, sa2382@cornell.edu  
**Program:** Break Through Tech AI Studio - Fall 2026  

---

## 🏢 About Cyera
Cyera operates in the data security and governance industry, focusing on providing comprehensive visibility and control over an organization's data landscape. Their team aims to help companies address critical challenges related to data security, compliance, and risk management in the modern enterprise.

---

## 🎯 The Challenge
### Project Summary
In this project, you will use enterprise SaaS metadata, browser/network activity logs, employee application usage data, and publicly available AI tool datasets along with NLP, embeddings, clustering, classification models, and LLM-based reasoning techniques to build a system that automatically discovers AI tools used across an organization, classifies their business purpose and risk level, and generates governance insights. This will help our company address the growing challenge of shadow AI adoption, compliance risk, data leakage exposure, and lack of visibility into enterprise AI usage.

### Success Criteria
Model performance metrics (Accuracy, precision, recall, and F1 score), multi-class classification accuracy, risk-scoring consistency, semantic retrieval relevance for the RAG assistant, and system functionality metrics, including dashboard filtering and trend reporting.

### Project Milestones
Use these milestones to guide your work. Your team will create a GitHub Projects board to track tasks within each milestone.
| Month | Milestone | Key Activities |
|-------|-----------|----------------|
| **September** | Data Exploration & Preprocessing | Detailed data profiling, cleaning of enterprise SaaS metadata and logs, and implementation of anomaly detection frameworks for user activity. |
| **October** | Feature Engineering & Baseline Modeling | Deriving features from unstructured and structured data, developing initial clustering models for AI tool categorization, and deploying standard classification algorithms. |
| **November** | Model Optimization & Evaluation | Iterative hyperparameter tuning for classification and NLP models, conducting validation runs using appropriate architectures, and assessing RAG system performance. |
| **December** | Insights, Deliverables & Presentation | Consolidating business recommendations on AI tool usage, optimizing the governance risk scoring engine, and packaging the final codebase with documentation and a presentation. |

> **Note for the team:** Please create a GitHub Projects board in this repository to break these milestones into weekly tasks. Go to the **Projects** tab → **New project** → Choose **Board** → Add columns for each month.

---

## 📊 Dataset
**Name and Source:** Publicly available AI tools database (Kaggle), enterprise SaaS metadata, browser/network activity logs, and employee application usage data.
**Format:** CSV, JSON, Logs (potentially requiring custom parsing)
**Size:** under 1gb  
**Location:** Accessible via Kaggle and provided internal data samples.

### Key Details
- Publicly available AI tools database (Kaggle), enterprise SaaS metadata, browser/network activity logs, and employee application usage data.
- Data may require significant preprocessing to harmonize formats and extract relevant features; specific attention will be needed for handling unstructured text logs and categorizing diverse SaaS applications.

---

## 🛠️ Suggested Approach
**ML Problem Type:** Classification / NLP & RAG / Clustering
**Recommended Libraries:**
- Classification
- Clustering
- Natural Language Processing (NLP)
- Large Language Models (LLMs)/ Generative AI
- RAG
- Embeddings
**Evaluation Metrics:** Strict validation benchmarks will include accuracy, precision, recall, F1 score for classification tasks, and semantic relevance scores for RAG components, with a trade-off analysis between model complexity and performance.

---

## 📚 Resources to Get Started
The following resources will help your team understand the problem space and potential technical approaches for this project:
**Background Reading:**
- Research papers and industry reports on "Shadow AI," "AI Governance," and "SaaS Management Platforms."
**Technical Tutorials:**
- Hugging Face Transformers documentation for NLP tasks, Scikit-learn documentation for classification and clustering, and guides on building RAG systems with LLMs.
**Code Examples:**
- GitHub repositories demonstrating AI tool classification, risk assessment frameworks, and RAG implementation patterns.

---

## 🤝 How We'll Work Together
**Check-ins:** During our biweekly 60-min AI Studio Lab Section meeting block (2nd and 4th week of every month)  
**Communication:** Slack channels and GitHub issues for project-related discussions.  
**Response time:** Expect a response within 24 business hours for non-urgent queries.  
**Recommended Tools:**
- **Coding:** Google Colab Free Tier  
- **Collaboration:** GitHub, Notion  
- **Virtual Meetings:** Zoom, Google Meet  

---

## 🚀 Getting Started
1. **Review this overview document** and note any questions for our first meeting.
2. **Begin reviewing the dataset** using the link provided in the Dataset section.
3. **Read the GitHub Projects documentation** [here](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects).

I'm excited to work with you!

---

## ❓ Questions?
Please bring any questions to our first meeting during the week of August 24th (Break Through Tech's Bridge to Studio - Session B).

---
