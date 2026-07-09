"""
CF Sniper - Codeforces Practice Assistant (Backend)
-----------------------------------------------------
Fetches a Codeforces user's profile + submissions + contest history,
cross-references the full problemset, and recommends 5 unsolved
problems rated 100-400 points above the user's current rating.
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import random
import time

app = Flask(__name__, template_folder=".")
CORS(app)  # Allow the frontend JS (fetch calls) to hit this API freely

CF_API_BASE = "https://codeforces.com/api"


@app.route("/")
def index():
    """Serve the single-page frontend."""
    return render_template("index.html")


@app.route("/api/analyze/<username>", methods=["GET"])
def analyze(username):
    """
    Main analysis endpoint.

    Steps:
      1. Fetch user.info -> basic profile (rating, rank, etc.)
      2. Fetch user.status -> every submission the user has made,
         used to build a set of already-solved problem IDs.
      3. Fetch user.rating -> full contest history, used to derive
         the user's peak rating and best (numerically lowest) rank
         ever achieved in a single contest, plus a rating trajectory
         for the chart.
      4. Fetch problemset.problems -> the entire CF problem catalogue.
      5. Filter down to problems the user hasn't solved that sit
         100-400 rating points above their current rating.
      6. Randomly sample 5 of those as the day's recommendations.
    """
    try:
        username = username.strip()
        if not username:
            return jsonify({"error": "Please provide a Codeforces handle."}), 400

        # --- 1. Fetch user info -----------------------------------------
        info_resp = requests.get(
            f"{CF_API_BASE}/user.info",
            params={"handles": username},
            timeout=10,
        )
        info_data = info_resp.json()

        if info_data.get("status") != "OK":
            return jsonify({"error": "User not found"}), 400

        user_info = info_data["result"][0]
        # Not everyone has a rating yet (brand new accounts) -> default to 0
        user_rating = user_info.get("rating", 0)
        user_rank = user_info.get("rank", "unrated")

        # --- 2. Fetch submissions -> build solved-problem set -----------
        status_resp = requests.get(
            f"{CF_API_BASE}/user.status",
            params={"handle": username},
            timeout=15,
        )
        status_data = status_resp.json()

        if status_data.get("status") != "OK":
            return jsonify({"error": "Could not fetch submission history"}), 400

        solved_set = set()
        for submission in status_data["result"]:
            if submission.get("verdict") == "OK":
                problem = submission["problem"]
                # Some problems (rare) don't have an index, guard with .get
                problem_id = f"{problem.get('contestId', '')}{problem.get('index', '')}"
                solved_set.add(problem_id)

        solved_count = len(solved_set)

        # --- 3. Fetch contest rating history ------------------------------
        # This endpoint 404s/returns FAILED for handles with zero rated
        # contests, so we treat that as "no history" rather than an error.
        peak_rating = user_rating
        best_rank = None
        rating_history = []

        rating_resp = requests.get(
            f"{CF_API_BASE}/user.rating",
            params={"handle": username},
            timeout=15,
        )
        rating_data = rating_resp.json()

        if rating_data.get("status") == "OK":
            contest_changes = rating_data["result"]
            for change in contest_changes:
                new_rating = change.get("newRating", 0)
                rank_in_contest = change.get("rank")

                if new_rating > peak_rating:
                    peak_rating = new_rating

                if rank_in_contest is not None:
                    if best_rank is None or rank_in_contest < best_rank:
                        best_rank = rank_in_contest

                rating_history.append({
                    "contestName": change.get("contestName", "Contest"),
                    "timestamp": change.get("ratingUpdateTimeSeconds", 0),
                    "rating": new_rating,
                    "rank": rank_in_contest,
                })

        # --- 4. Fetch the full problem set ------------------------------
        problems_resp = requests.get(
            f"{CF_API_BASE}/problemset.problems",
            timeout=15,
        )
        problems_data = problems_resp.json()

        if problems_data.get("status") != "OK":
            return jsonify({"error": "Could not fetch problem set"}), 400

        all_problems = problems_data["result"]["problems"]

        # --- 5. Filter candidates ----------------------------------------
        lower_bound = user_rating + 100
        upper_bound = user_rating + 400

        candidates = []
        for problem in all_problems:
            rating = problem.get("rating")
            if rating is None:
                continue  # skip problems without a rating (e.g. some gym problems)

            if not (lower_bound <= rating <= upper_bound):
                continue

            problem_id = f"{problem.get('contestId', '')}{problem.get('index', '')}"
            if problem_id in solved_set:
                continue

            candidates.append(problem)

        if not candidates:
            return jsonify({
                "error": "No unsolved problems found in that rating window. "
                         "Try a different handle or check back after new problems are added."
            }), 400

        # --- 6. Sample 5 recommendations ----------------------------------
        sample_size = min(5, len(candidates))
        recommendations_raw = random.sample(candidates, sample_size)

        recommendations = []
        for problem in recommendations_raw:
            contest_id = problem.get("contestId")
            index = problem.get("index")
            recommendations.append({
                "name": problem.get("name"),
                "rating": problem.get("rating"),
                "contestId": contest_id,
                "index": index,
                "link": f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
            })

        return jsonify({
            "username": user_info.get("handle", username),
            "rating": user_rating,
            "peak_rating": peak_rating,
            "best_rank": best_rank,
            "solved_count": solved_count,
            "rank": user_rank,
            "rating_history": rating_history,
            "recommendations": recommendations,
        })

    except requests.exceptions.RequestException:
        return jsonify({"error": "Could not reach Codeforces servers. Try again shortly."}), 400
    except Exception:
        return jsonify({"error": "Something went wrong while analyzing this handle."}), 400


if __name__ == "__main__":
    app.run(debug=True, port=5000)
