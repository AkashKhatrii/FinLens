/* FinLens term glossary. Keys are normalised: lowercase, letters+digits only. */
(function (root) {
  const GLOSSARY = {};

  function norm(s) {
    return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  }

  function put(keys, title, what, here) {
    const entry = { title, what, here };
    keys.forEach((k) => { GLOSSARY[norm(k)] = entry; });
  }

  put(["overall"], "Overall score",
    "A single 0–100 headline made by blending the three holding-period scores.",
    "FinLens weights long-term 50%, swing 30%, short-term 20%. It is not a fourth independent analysis.");

  put(["short", "shortterm", "short term"], "Short term",
    "A holding period of days to about three weeks — a trade, not an investment.",
    "Chart setup, trend, and risk dominate. Business quality barely counts. Buy here means the tape looks tradeable, not that the company is great.");

  put(["swing"], "Swing",
    "A holding period of roughly 1–3 months, usually into the next results.",
    "Trend, earnings momentum, and a bit of valuation matter. The idea is to ride an existing move, not to own the business forever.");

  put(["long", "longterm", "long term"], "Long term",
    "A holding period of 1–3+ years — own the business.",
    "Profitability, growth, valuation, and the balance sheet dominate. The chart is almost ignored.");

  put(["confidence"], "Confidence",
    "How much to trust that horizon’s score, separately from the score itself.",
    "High when most of the weighted data exists and the pillars agree. Missing inputs or pillars that contradict each other lower confidence, not the score.");

  put(["growth"], "Growth",
    "Whether sales and profit are expanding, over a year and over several years.",
    "Scored from revenue/profit YoY, multi-year CAGR, and the latest quarter vs the same quarter last year. Heavy weight on the long-term score.");

  put(["profitability", "profitabilityreturns"], "Profitability & Returns",
    "How much of each rupee of sales and capital the company keeps.",
    "Operating and net margin, whether margins are expanding, plus ROE and ROCE. The biggest long-term pillar.");

  put(["health", "balancesheetcash", "balance sheet & cash"], "Balance sheet & cash",
    "Whether the company can pay its bills and whether reported profit turns into cash.",
    "Debt ratios, interest cover, current ratio, operating cash vs profit, and free-cash-flow margin. Missing data here is skipped, not scored as zero.");

  put(["valuation"], "Valuation",
    "Whether today’s price is demanding or cheap for this business.",
    "P/E vs the company’s own 5-year median, P/B, EV/EBITDA, PEG, earnings yield vs the 10-year G-Sec, and a DCF when free cash flow is positive.");

  put(["technicalshort", "shorttermsetup"], "Short-term setup",
    "How the stock is behaving over days — stretched, washed out, or in play.",
    "RSI, Bollinger %B, distance from the 20-day average, 1-week return, and volume. 40% of the short-term score, 0% of long-term.");

  put(["technicaltrend", "trendrelativestrength", "trend & relative strength"], "Trend & relative strength",
    "Whether the medium-term trend is up and whether the stock is beating the index.",
    "Price vs 50- and 200-day averages, ADX, 3-month and 1-year relative strength vs Nifty, and 52-week range position.");

  put(["earnings", "earningsmomentum"], "Earnings momentum",
    "Whether recent results have been beating or missing what the street expected.",
    "Beat rate and average surprise over the last four quarters. Matters most for swing trades into the next print.");

  put(["sentiment", "sentimentownership"], "Sentiment & ownership",
    "What analysts and owners are doing, not what the statements say.",
    "Street rating and target, promoter (insider) holding, and institutional holding. A weak signal, but falling promoter stake is treated as a warning.");

  put(["risk"], "Risk",
    "How violently the stock moves and how easy it is to get in or out.",
    "Beta, volatility, 3-year max drawdown, and daily turnover. Scored as its own pillar so a cheap stock that can halve still looks dangerous.");

  put(["revyoy", "revenuegrowthyoy"], "Revenue growth (YoY)",
    "This year’s sales versus last year’s, as a percent.",
    "Computed from the income statement, not a summary field. Sign-flips from a loss year are left blank rather than shown as a nonsense percent.");

  put(["revcagr", "revenuecagr"], "Revenue CAGR",
    "Compound annual growth rate of sales over several years — the smoothed pace of growth.",
    "Needs a positive starting base. A cyclical at peak earnings can still print a high CAGR; the AI layer is told to flag that.");

  put(["patyoy", "netprofitgrowthyoy"], "Net profit growth (YoY)",
    "This year’s profit after tax versus last year’s.",
    "Same date-matched logic as revenue. A jump from a tiny base scores well on the band even if the business is still small.");

  put(["patcagr", "profitcagr"], "Profit CAGR",
    "Compound annual growth of net profit over several years.",
    "Undefined if an earlier year was a loss. Weighted slightly more than revenue CAGR because earnings growth is what you get paid on.");

  put(["qrevyoy", "latestquarterrevenueyoy"], "Latest quarter revenue (YoY)",
    "The newest reported quarter versus the same quarter a year ago.",
    "Matched by date, not by column position — Yahoo sometimes skips a quarter. If no year-ago column is found, this metric is skipped.");

  put(["qpatyoy", "latestquarterprofityoy"], "Latest quarter profit (YoY)",
    "Newest quarter’s net profit versus the same quarter last year.",
    "A check on whether the annual numbers are inflecting. Same date-matching rule as quarterly revenue.");

  put(["opmargin", "operatingmargin"], "Operating margin",
    "Operating profit as a percent of sales — the core business before interest and tax.",
    "Higher is better. ~16% scores around 72; 25%+ is excellent. Trend is scored separately so one fat year does not hide compression.");

  put(["netmargin"], "Net margin",
    "Profit after everything (interest, tax, one-offs) as a percent of sales.",
    "Useful, but easier to dress up than operating margin. FinLens also watches whether that profit becomes cash.");

  put(["margintrend"], "Margin trend",
    "Whether operating margins have been expanding or shrinking over recent years.",
    "A gentle slope of the margin series, not a single quarter. Expanding margins score well; a slow bleed is a long-term negative.");

  put(["roe", "returnonequity"], "Return on equity (ROE)",
    "Profit as a percent of shareholders’ equity — how hard the book value is working.",
    "A star long-term metric (weight 1.8). ~18% scores about 74. Very high ROE can be a shrinking-equity artefact after buybacks; the note flags that.");

  put(["roce", "returnoncapitalemployed"], "Return on capital employed (ROCE)",
    "Profit versus all capital in the business, debt included — not just equity.",
    "Compared in the note to a ~12% cost of capital. If ROCE is above that, growth is usually value-accretive. Same weight as ROE.");

  put(["debtequity", "debt / equity"], "Debt / equity",
    "How much the company owes relative to what shareholders own.",
    "Lower is better. 0.5× is comfortable; above ~1.8× scores poorly. Meaningless if equity is negative — then it is skipped.");

  put(["netdebtebitda"], "Net debt / EBITDA",
    "Net borrowings (debt minus cash) divided by annual operating earnings. Years to pay off debt from earnings.",
    "Below 1× is healthy; above 3.5× is stretched. Not meaningful for banks — the AI is told to ignore it there.");

  put(["interestcover", "interestcoverage"], "Interest coverage",
    "Operating profit divided by interest expense — how many times over the company can pay its lenders.",
    "Below ~2.5× is a solvency warning. High coverage scores well on the balance-sheet pillar.");

  put(["currentratio"], "Current ratio",
    "Current assets divided by current liabilities — can it pay bills due this year?",
    "Around 1.5–2.2× is healthy. Very high (4×+) scores a bit worse because idle cash is not being used.");

  put(["ocftopat", "operatingcashflowprofit"], "Operating cash flow / profit",
    "Cash generated by the business versus the profit it reported.",
    "Near 1× means earnings are real. Persistently below ~0.8× is the classic Indian mid-cap accounting red flag. Heavily weighted.");

  put(["fcfmargin", "freecashflowmargin"], "Free cash flow margin",
    "Cash left after running the business and investing in it, as a percent of sales.",
    "Negative FCF also blocks the DCF — FinLens will not invent a fair value for a cash-burning company.");

  put(["pe", "p/e", "p/e (trailing)", "trailing pe"], "P/E (price / earnings)",
    "Share price divided by earnings per share — how many years of current profit the market is paying for.",
    "Lower is cheaper. Compared both in absolute bands and versus this company’s own 5-year median, not versus peers.");

  put(["pevsown5ymedian", "pevshistory", "pe_vs_history"], "P/E vs own 5-year median",
    "How expensive the stock is relative to how it has usually been valued, not relative to other companies.",
    "Below its own median scores well. A cyclical often looks ‘cheap vs history’ at the earnings peak — that is a trap the AI is told to catch.");

  put(["5ymedianpe", "5y median p/e"], "5-year median P/E",
    "The typical trailing P/E this stock has traded at over the last five years.",
    "Shown as a reference next to today’s P/E. The scored metric is how far today’s P/E sits from this median, not the median itself.");

  put(["pb", "p/b", "price / book", "pricebook"], "Price / book",
    "Price divided by accounting book value per share.",
    "More useful for banks and holding companies than for asset-light software. Negative book value is not scored as a bargain.");

  put(["evebitda", "ev / ebitda"], "EV / EBITDA",
    "Enterprise value (market cap plus net debt) divided by operating earnings before depreciation.",
    "Lower is cheaper. Ignored conceptually for banks/NBFCs; the number may still appear — treat it as inappropriate there.");

  put(["peg", "pegratio", "peg ratio"], "PEG ratio",
    "P/E divided by expected or historical earnings growth. Adjusts a high P/E for fast growth.",
    "Around 1× is ‘fair growth’. Above ~2.5× scores poorly: you are paying a lot for each unit of growth.");

  put(["earningsyield10ygsec", "earningsyieldspread", "earnings yield − 10y g-sec"], "Earnings yield vs 10Y G-Sec",
    "Earnings as a percent of price, minus the Indian 10-year government bond yield.",
    "If the bond pays more than the stock’s earnings, the equity needs growth to justify itself. Compared to G-Sec, not to US Treasuries.");

  put(["dividendyield", "divyield", "div yield"], "Dividend yield",
    "Dividends per share as a percent of the current price.",
    "A light weight in valuation. High yield can mean a cheap stock or a business that cannot grow.");

  put(["dcfupside", "dcf value", "dcf upside", "dcf"], "DCF (discounted cash flow)",
    "A model that values the company as today’s worth of expected future free cash flows.",
    "Two-stage, shown with all assumptions. Refuses to run on negative FCF. Long-term target in the plan is this fair value, not a chart level.");

  put(["rsi", "rsi14", "rsi (14)"], "RSI (14)",
    "Relative Strength Index — a 0–100 oscillator of recent up vs down days. Not ‘strength vs the index’.",
    "Scored as a hill: mid-range is good for a buy; overbought (~70+) and oversold are both penalised, overbought more so.");

  put(["pctb", "bollingerb", "bollinger %b"], "Bollinger %B",
    "Where price sits inside a volatility band around the average. 0 = lower band, 1 = upper band.",
    "Near 0.5 is mid-channel. Stuck above 1 is extended; below 0 is washed out. Used only in the short-term setup.");

  put(["vssma20", "pricevs20dma", "20dma", "20-dma"], "Price vs 20-DMA",
    "How far the price is from its 20-day moving average — a short trend line.",
    "A few percent above scores well. Far above is chasey; far below is broken. 20-DMA is also the short-term entry reference.");

  put(["ret1w", "1weekreturn"], "1-week return",
    "Price change over the last week.",
    "Gentle strength scores better than a vertical spike. A crash week scores poorly for a short-term buy.");

  put(["volumeratio", "volumetrend20d50d"], "Volume trend",
    "Recent average volume versus a longer average — is participation picking up?",
    "Rising volume confirming a move scores well. Thinning volume is a warning that the move has no crowd behind it.");

  put(["vssma200", "pricevs200dma", "200dma", "200-dma"], "Price vs 200-DMA",
    "Distance from the 200-day moving average — the long-term trend line.",
    "Above is a bull market for this stock; below is a bear trend. A death cross (50-DMA below 200) is noted in technicals.");

  put(["vssma50", "pricevs50dma", "50dma", "50-dma"], "Price vs 50-DMA",
    "Distance from the 50-day moving average — the swing trend.",
    "The swing plan uses the 50-DMA as an exit: losing it (and the ATR stop) is the signal to get out.");

  put(["adx14", "trendstrengthadx", "adx"], "ADX",
    "Average Directional Index — how strong the trend is, not whether it is up or down.",
    "Below ~20 is chop (hard to swing-trade). 25–40 is a real trend. Extremely high ADX can mean the move is exhausted.");

  put(["rs3m", "3mvsbenchmark", "vsindex3m"], "3-month vs benchmark",
    "How much this stock beat or lagged the Nifty over three months.",
    "Outperformance scores well on trend. A great business lagging the index still looks weak here — that is the point of a separate long-term score.");

  put(["rs1y", "1yvsbenchmark"], "1-year vs benchmark",
    "One-year relative performance versus the Nifty.",
    "Same idea as 3-month, slower. A −20% relative year is a heavy trend-pillar drag even if fundamentals are fine.");

  put(["week52position", "positionin52wrange", "52w"], "Position in 52-week range",
    "Where today’s price sits between the 1-year low (0%) and high (100%).",
    "Mid-to-high is healthier than a new low. Right at the high scores a bit worse (extended). Not the same as ‘near a 52-week high is always good’.");

  put(["beta", "betavsindex"], "Beta",
    "How much the stock typically moves when the index moves 1%. Beta 1 ≈ the market; 1.3 is jumpy.",
    "Computed from history vs Nifty, not taken from Yahoo’s often-wrong `.info` beta. Lower beta scores better on the risk pillar.");

  put(["volatility", "annualisedvolatility"], "Volatility",
    "How large typical daily moves are, scaled to a year.",
    "A risk input. High vol lowers the risk score and also feeds the DCF discount rate via beta.");

  put(["maxdrawdown", "maxdrawdown3y"], "Max drawdown (3Y)",
    "The worst peak-to-trough fall in the last three years.",
    "A −50% print means you had to sit through a halving. Position size should respect that, even if the long-term score is a Buy.");

  put(["liquidity", "avgdailyturnover", "turnoverday"], "Average daily turnover",
    "How many rupees typically trade in a day.",
    "Thin names score poorly: you cannot exit in a hurry without moving the price. Shown in ₹ crore per day.");

  put(["beatrate", "beatratedlast4"], "Beat rate",
    "Share of the last four quarters where reported earnings beat the consensus estimate.",
    "4/4 is excellent swing/earnings momentum. A miss streak into the next print is a short-term risk.");

  put(["avgsurprise"], "Average surprise",
    "Average percent by which results beat (or missed) estimates over those quarters.",
    "Small consistent beats score better than one huge beat and three misses.");

  put(["analystrating", "streetrating"], "Street rating",
    "The consensus analyst recommendation (buy / hold / sell) and how many analysts are on the stock.",
    "Mapped to a score. A ‘buy’ from 40 analysts is sentiment, not a fact about the business — hence a light weight.");

  put(["analystupside", "upsidetotarget"], "Upside to target",
    "Percent gap between the current price and the average analyst target.",
    "Positive upside scores well on sentiment. Targets often lag the tape, so this can look cheap after a crash for the wrong reason.");

  put(["promoterholding", "promoterinsiderholding"], "Promoter / insider holding",
    "Percent of the company owned by promoters (founders/controlling shareholders) or insiders.",
    "In India this is a first-order governance signal. High and stable is good; falling or pledged stake is a warning. Pledge is often missing from this feed.");

  put(["institutionalholding"], "Institutional holding",
    "Percent owned by mutual funds, insurers, FIIs, and similar.",
    "Some institutional ownership is a quality tell. It is a weak pillar — not a reason to buy by itself.");

  put(["stop", "stoploss"], "Stop loss",
    "A price where the short/swing thesis is wrong and you should exit.",
    "Short term: ATR-based. Swing: the lower of that stop and the 50-DMA. Long term has no stop — you review the thesis, not a tick.");

  put(["target"], "Target",
    "A first take-profit or fair-value level for that horizon.",
    "Short: recent range high. Swing: a bit beyond resistance. Long: the DCF value, to accumulate toward, not a day-trade exit.");

  put(["rr", "r:r", "riskreward"], "Risk / reward (R:R)",
    "Upside to target divided by downside to the stop. 2 means you make ₹2 for every ₹1 you risk.",
    "Only shown when both a stop and a target exist. Below 1 is a poor trade even if the score says Buy.");

  put(["yoy"], "YoY (year on year)",
    "This period versus the same period last year, so seasonality does not distort the comparison.",
    "Quarters are matched by date (± ~6 weeks). If last year’s quarter is missing, FinLens reports nothing instead of a fake number.");

  put(["cagr"], "CAGR",
    "Compound annual growth rate — the constant yearly rate that gets you from the oldest figure to the newest.",
    "Needs a positive base year. A bounce from a crash can print a huge CAGR that is not a sustainable growth rate.");

  put(["fcf", "freecashflow"], "Free cash flow (FCF)",
    "Cash from operations minus the capex needed to maintain and grow the business.",
    "The DCF’s raw material. Negative FCF → no DCF. Also scored as FCF margin on the health pillar.");

  put(["gsec", "10ygsec", "10-year g-sec"], "10-year G-Sec",
    "The Indian government’s 10-year bond yield — the local risk-free rate.",
    "Used in the DCF discount rate and versus earnings yield. Never compared to US Treasury yields.");

  put(["atr"], "ATR (average true range)",
    "How many rupees the stock typically moves in a day, including gaps.",
    "The short-term stop sits about 2× ATR below price, so normal noise should not kick you out.");

  put(["mcap", "marketcap"], "Market cap",
    "Share price × shares outstanding — the market’s value of the equity.",
    "Shown in ₹ crore. Used in EV (with net debt) for EV/EBITDA.");

  put(["cr", "crore"], "Crore",
    "Indian unit: 1 crore = 10 million rupees.",
    "Statement amounts and market cap in FinLens are in ₹ Cr unless labelled otherwise.");

  put(["1m", "1month", "1mreturn"], "1-month return",
    "How much the share price moved over the last calendar month.",
    "Shown on the chart strip as context, not scored on its own. Short-term scoring uses the 1-week return instead.");

  put(["1y", "1year", "1yreturn"], "1-year return",
    "Price change over the last twelve months.",
    "Context on the chart. The trend pillar uses 1-year relative strength versus the Nifty, which is this move minus the index move.");

  put(["52whigh", "52weekhigh"], "52-week high",
    "The highest close in the last year.",
    "The header shows how far the stock has fallen from that high. Separate from ‘position in the 52-week range’ on the trend pillar.");

  put(["discountrate", "discounted", "wacc"], "Discount rate",
    "The yearly rate used to bring future cash back to today’s rupees. A higher rate cuts today’s value.",
    "FinLens uses a CAPM-style rate: 10-year G-Sec plus beta times an equity risk premium. Jumpy stocks get a harsher DCF.");

  put(["terminalgrowth"], "Terminal growth",
    "The perpetual growth rate assumed after the explicit forecast years of a DCF.",
    "Capped near long-run nominal GDP. Inflating this number is the usual way to fake a high fair value — FinLens does not let it run away.");

  put(["metric"], "Metric",
    "One measured input — a ratio, a growth rate, or a market figure — that feeds a pillar score.",
    "Each metric is banded to 0–100. Missing inputs are skipped (they cut confidence, not the score). Click a name for what it means here.");

  put(["metricscore", "score"], "Metric score",
    "That metric mapped onto 0–100 using FinLens’s bands, not a percentile versus other companies.",
    "Green is roughly 70+. Grey dash means the input was missing. The pillar score is the weighted average of the metrics that actually printed.");

  put(["strongbuy"], "Strong Buy",
    "The most bullish verdict band.",
    "Overall or horizon score at or above 80. Still not advice — it means the weighted evidence in that window is very strong.");

  put(["buy"], "Buy",
    "A bullish verdict, short of Strong Buy.",
    "Score at or above 66 and below 80. For short-term this is about the tape; for long-term it is about the business.");

  put(["hold"], "Hold",
    "Neither a clear buy nor a clear sell on this evidence.",
    "Score 50–65. Common when quality is fine but valuation is full, or the other way around.");

  put(["reduce"], "Reduce",
    "The evidence leans negative — trim or avoid adding.",
    "Score 35–49. Not the same as Avoid; something is working, but not enough to own more.");

  put(["avoid"], "Avoid",
    "The weakest verdict band.",
    "Score below 35. High risk, poor quality, or a very expensive tape for that horizon.");

  root.GLOSSARY = GLOSSARY;
  root.termNorm = norm;
  root.termEntry = function (id) {
    if (id == null || id === "") return null;
    return GLOSSARY[norm(id)] || null;
  };
  root.termCatalog = function () {
    const seen = new Set();
    const out = [];
    Object.keys(GLOSSARY).forEach((k) => {
      const e = GLOSSARY[k];
      if (seen.has(e)) return;
      seen.add(e);
      out.push(e);
    });
    out.sort((a, b) => a.title.localeCompare(b.title));
    return out;
  };
})(window);
