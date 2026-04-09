# PRESENTATION SPEAKER SCRIPT
## Intelligent Pharmacy Inventory Management
### ~5 Minutes | Print This Out & Keep It On The Podium

---

## SLIDE 1 — Title (15 seconds)

> Good [morning/afternoon] everyone. My name is [NAME], and along with [TEAMMATES], we're presenting our capstone project: **Intelligent Pharmacy Inventory Management**.
>
> In short — we built a machine learning system that tells pharmacists exactly *when* and *how much* to reorder, while making sure we **never** run out of a patient's medication.

---

## SLIDE 2 — The Problem (45 seconds)

> So here's the core tension every pharmacy faces. We call it the **Optimization Paradox**.
>
> On one side, you have **stockouts**. If a patient walks in to refill their blood pressure medication and you don't have it — that's not just lost revenue. That's a **health risk**. They could miss doses. They could switch pharmacies permanently.
>
> On the other side, you have **wastage**. Medications expire. If you over-order, those drugs sit on the shelf, expire, and get destroyed. For an independent pharmacy, that's thousands of dollars a year — literally thrown in the trash.
>
> And here's the kicker — most pharmacies today still use **manual min/max rules**. A pharmacist looks at the shelf, sees it's low, and places an order. No seasonality. No data. Just gut feeling.
>
> **Our project replaces that gut feeling with machine learning.**

---

## SLIDE 3 — Literature Review (45 seconds)

> Before we built anything, we looked at what the industry is already doing.
>
> **Traditionally**, pharmacies use things like ABC/XYZ analysis — that's classifying drugs by revenue and demand variability — and Vendor Managed Inventory, where wholesalers like McKesson manage stock levels for you. The problem? VMI optimizes for the *wholesaler*, not the *pharmacy*.
>
> On the **ML side**, there's solid recent work. Rathipriya and colleagues used Facebook Prophet — the same model we use — on retail pharmacy data and got 12 to 18 percent MAPE for chronic medications. Oliveira's group at a hospital compared Prophet against LSTM and XGBoost and found Prophet performed comparably with way less tuning.
>
> **CVS Health** is doing this at scale with gradient-boosted trees and prescription refill cycle data.
>
> **Where we fit in**: we combine Prophet's forecasting power with something most of these studies are missing — **asymmetric cost functions** that treat stockouts and wastage differently. That's our key contribution.

---

## SLIDE 4 — Why MAPE Is Not Enough (40 seconds)

> Now, our original proposal used MAPE — Mean Absolute Percentage Error — as our primary metric. And it's a good metric for *accuracy*.
>
> But here's the problem: **MAPE is symmetric**. It penalizes over-predicting by 10 units the exact same as under-predicting by 10 units.
>
> In the real world, those are **completely different situations**. If I over-predict and order 10 extra units of Amoxicillin — okay, I have some extra holding cost, maybe a small expiration risk. Minor.
>
> But if I under-predict by 10 units? Patients can't fill their prescriptions. I'm making emergency calls to the wholesaler. I'm paying expedited shipping. And worst case — a patient leaves and never comes back.
>
> So we needed a metric that **knows** a stockout is way worse than having a few extra pills on the shelf. That's what led us to define explicit cost functions.

---

## SLIDE 5 — Cost Functions (50 seconds)

> We defined two cost functions. Let me walk through them simply.
>
> **Wastage cost** kicks in when you order *more* than you needed. It's the number of excess units, times the cost of each unit expiring plus the daily cost of storing it. For most drugs, this works out to **pennies per unit**.
>
> **Stockout cost** kicks in when demand exceeds what you ordered. And this is where the **alpha multiplier** comes in. We set alpha to 10 — meaning the model treats a stockout as **ten times more expensive** than holding an extra unit. On top of that, you add the emergency reorder cost and the estimated revenue you lose if that patient switches pharmacies.
>
> Here's a concrete example with Amoxicillin. Same 10-unit error, two directions:
>
> - Over-predict by 10? Costs you **55 cents**.
> - Under-predict by 10? Costs you **$400**.
>
> That's a **727x difference**. And that's exactly the behavior we want — the system will always prefer to slightly over-order rather than risk a single stockout. **Patient safety first.**

---

## SLIDE 6 — Technical Architecture (40 seconds)

> Here's how it all connects. The top row is our forecast pipeline — synthetic data goes through preprocessing, into Facebook Prophet, which produces a 30-day probabilistic forecast.
>
> The **new layer** — shown at the bottom in red — is the cost optimization. The forecast's prediction intervals feed into both cost functions. We evaluate candidate order quantities across that distribution and pick the one that **minimizes total expected cost**.
>
> Because of that alpha equals 10 penalty, the optimal order quantity Q-star consistently lands near the **80th to 90th percentile** of the predicted demand — not the median. That's the mathematical mechanism that ensures we prioritize patient safety.
>
> And all of this is surfaced through a **Streamlit dashboard** where a pharmacist can see real-time reorder alerts for all 8 medications.

---

## SLIDE 7 — Who Else Is Doing This (30 seconds)

> Quick landscape scan — who else is using time-series methods in pharmacy?
>
> CVS Health is the biggest player — they use gradient-boosted trees with prescription refill data. Rathipriya's group proved Prophet works well for retail pharmacy. Oliveira showed it holds up against deep learning in hospitals. And the major wholesalers — McKesson, AmerisourceBergen — run VMI systems, but those optimize for *their* logistics, not the pharmacy's patients.
>
> **Our differentiator**: we're the only approach that combines Prophet forecasting with explicit asymmetric cost penalties, and we're designing it to be open-source and pharmacy-centric.

---

## SLIDE 8 — Evaluation & Timeline (30 seconds)

> We evaluate on **three axes**, not just one. Forecast accuracy via MAPE — we're targeting under 20 percent for chronic drugs. Business cost via our asymmetric loss function. And service level — we want a fill rate above 95 percent, meaning 95 percent of demand is met from existing stock.
>
> The timeline is 10 weeks. Data generation and EDA are done. We're now in the modeling and cost function implementation phase, with the dashboard and final report coming in weeks 9 and 10.

---

## SLIDE 9 — Thank You (15 seconds)

> To wrap up — we started with a simple idea: help pharmacists order smarter. But by layering **asymmetric cost functions** on top of **time-series forecasting**, we've built something that doesn't just predict demand — it makes **cost-aware decisions** that put patient safety first.
>
> Thank you. We're happy to take questions.

---
---

\newpage

# CHEAT SHEET: LIKELY QUESTIONS & STRONG ANSWERS
## Print This On The Back / Second Page

---

### Q1: "Why did you choose alpha = 10? Why not 5 or 20?"

> Great question. The value of 10 comes from pharmaceutical supply chain literature — specifically Uthayakumar and Priyan (2013), who found stockout penalties in pharmacy settings range from 5x to 15x the holding cost. We chose 10 as a reasonable midpoint. In practice, alpha is a **tunable parameter** — a pharmacy with very expensive medications might set it higher, while one with easily substitutable generics might set it lower. The framework is flexible.

---

### Q2: "Your MAPE values are above 20%. Doesn't that mean the model isn't working?"

> Fair point. Our current MAPE ranges from about 24% for stable drugs like Metformin up to 57% for highly seasonal drugs like Cetirizine. Two things to note: First, this is on **synthetic data with intentionally high noise** — Poisson-distributed daily variation on top of seasonality. Real pharmacy data with actual prescription refill patterns would likely be smoother. Second — and this is the key insight from our revision — **MAPE alone doesn't determine business performance**. Even a model with 30% MAPE can produce excellent business outcomes if the cost functions are properly calibrated. That's exactly why we moved beyond MAPE to asymmetric loss as our primary business metric.

---

### Q3: "How is this different from what CVS or McKesson already does?"

> CVS and McKesson have massive proprietary systems. Three key differences: First, their systems are **closed-source and proprietary** — an independent pharmacy can't use them. Second, VMI systems like McKesson's optimize for the **wholesaler's** logistics, not the pharmacy's patients. Third, we specifically designed **asymmetric cost functions** that encode the clinical priority of never running out of a maintenance medication. Most commercial systems optimize for revenue or logistics efficiency, not patient safety as a first-class objective.

---

### Q4: "You're using synthetic data. How do you know this would work on real pharmacy data?"

> Excellent question. Our synthetic data generator is calibrated against CDC FluView surveillance data for seasonal patterns and CMS public data for prescription volume distributions. The weekly patterns — Monday surge, weekend dip — mirror real pharmacy operations. That said, synthetic data is a **limitation** we acknowledge. The architecture is designed so that swapping in real data requires changing only the data ingestion layer — the Prophet models, cost functions, and decision engine are data-agnostic. If we had access to a pharmacy's POS system, we could retrain in hours.

---

### Q5: "Why Prophet and not ARIMA, LSTM, or XGBoost?"

> We evaluated the literature before choosing. Prophet has three advantages for pharmacy data: **(1)** It handles **missing data and outliers** gracefully — pharmacies have gaps on holidays and during stockouts. **(2)** It natively produces **prediction intervals**, which we need for the cost function optimization — ARIMA gives you point forecasts, and getting reliable intervals from LSTM is much harder. **(3)** It's **interpretable** — we can show the pharmacist "this spike is because of flu season plus a Monday effect," which builds trust. Oliveira et al. (2023) confirmed Prophet performs comparably to LSTM for pharmaceutical data with significantly less tuning.

---

### Q6: "What happens if the expiration probability estimate is wrong?"

> The wastage function includes p_exp — the probability a unit expires before sale. In practice, this would be estimated from the drug's shelf life and the pharmacy's historical turnover rate. If we overestimate p_exp, the system becomes slightly more conservative (orders less). If we underestimate it, we order a bit more. But here's the key: because the **stockout penalty dominates** (alpha = 10), even large errors in p_exp have minimal impact on the final order quantity. The system is robust to wastage parameter uncertainty — it's designed that way deliberately.

---

### Q7: "How would you implement this in a real pharmacy setting?"

> The Streamlit dashboard is our proof-of-concept interface. For a real deployment, you'd connect it to the pharmacy's **point-of-sale system** for real-time sales data, and to their **wholesaler's EDI feed** for automated ordering. The model retrains nightly on the latest 2 years of data. A pharmacist would open the dashboard each morning, see which drugs need reordering, and approve the suggested quantities. Over time, as the system builds trust, you could automate low-risk orders entirely and only flag high-cost or unusual recommendations for human review.

---

### Q8: "What's the business case? How much money does this actually save?"

> An independent pharmacy doing $3-5 million in annual revenue typically loses 2-5% to inventory shrinkage — that's $60,000 to $250,000 per year in expired drugs and emergency reorders. Even a 30% reduction in waste through better forecasting saves $20,000-$75,000 annually. On the stockout side, each lost patient represents $2,000-$5,000 in annual prescription revenue. Preventing even 10 patient defections per year saves $20,000-$50,000. The system effectively pays for itself within months.

---

### Q9: "Why 8 drugs? Why these specific ones?"

> We selected 8 drugs that represent the **key demand archetypes** in a community pharmacy. Metformin and Lisinopril are **stable chronic medications** — high volume, predictable. Amoxicillin and Azithromycin are **seasonal antibiotics** — they spike in winter. Cetirizine is a **seasonal allergy drug** — spring spike. Albuterol is **weather-sensitive**. Sertraline has a **winter SAD pattern**. And Omeprazole is a **high-volume OTC-adjacent** drug. Together, these 8 cover every major demand pattern a pharmacy sees. If the model works across all 8 archetypes, it generalizes.

---

### Q10: "How do you handle the lead time variability in your reorder logic?"

> Currently we use a fixed lead time per drug from our configuration — typically 2-3 days for common generics. The safety stock calculation accounts for this: Reorder Point = (Lead Time × Average Demand) + (Safety Stock Days × Average Demand). In a production system, you'd estimate lead time distributions from historical order-to-delivery data and incorporate that uncertainty into the cost function optimization. That's a natural next step — moving from deterministic lead times to stochastic ones.

---

### GENERAL TIPS FOR Q&A:

1. **If you don't know the answer**: "That's a great question — it's outside the scope of what we implemented, but here's how I'd approach it..."
2. **If it's a criticism**: Acknowledge it. "You're absolutely right that's a limitation. We addressed it by..." or "That's something we'd tackle in the next iteration."
3. **Bridge back to your key message**: Always end answers by connecting back to: "...and that's why the asymmetric cost approach is important — it keeps patient safety as the top priority."
4. **Numbers impress**: Drop specific numbers whenever you can. "$400 vs 55 cents." "727x difference." "Alpha of 10." "80th to 90th percentile."
