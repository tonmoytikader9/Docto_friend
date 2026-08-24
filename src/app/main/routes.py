import csv,requests
import os, json
import random
from datetime import datetime
from io import BytesIO
from pathlib import Path
from flask import (
    render_template,
    request,
    current_app,
    jsonify,
    session,
    redirect, 
    url_for,
    send_file,
)
from . import bp
from ..db_manager import doctor_database_management,clinic_database_management,patient_database_management,medicine_database_management
from ..db_manager import db_operations
from dotenv import dotenv_values
from datetime import datetime, date, time, timedelta, timezone
import zoneinfo
import os
from tempfile import NamedTemporaryFile
import subprocess
import logging

logger = logging.getLogger(__name__)

HERE = os.path.dirname(__file__)                      # .../src/app/main
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))  # moves up to project root
SNAPSHOT_PATH = os.path.join(PROJECT_ROOT, "index.html")

print("''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''")
print(f"project directory {HERE}")
print(f"Project root {PROJECT_ROOT}")
print(f"index.html path in project {SNAPSHOT_PATH}")
print("''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''")

def get_iso_week(dt):
    """
    Compute ISO year/week using the date components in IST.
    Accepts date or datetime; uses IST-local date (year/month/day) to construct
    an IST-midnight datetime and then follows ISO week rules.
    Returns {'year': int, 'week': int}.
    """
    # If datetime, convert to IST then take date; if date, use directly
    if isinstance(dt, datetime):
        dt_ist = dt.astimezone(IST)
        d = dt_ist.date()
    else:
        d = dt  # assume date

    # Construct IST-midnight for that local date
    d_ist_mid = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=IST)

    # ISO weekday: Mon=1 .. Sun=7
    day_num = d_ist_mid.isoweekday()

    # Move to Thursday of this week (IST)
    d_thu_ist = d_ist_mid + timedelta(days=(4 - day_num))

    # Jan 1 of that ISO-year at IST midnight
    year_start_ist = datetime(d_thu_ist.year, 1, 1, 0, 0, 0, tzinfo=IST)

    days_diff = (d_thu_ist - year_start_ist).days
    week_no = (days_diff + 1 + 6) // 7

    return {'year': d_thu_ist.year, 'week': week_no}

def gitsubprocess(REPO_PATH=PROJECT_ROOT):
    '''
        Pushing profile to git on change automatic
    '''
    try:
        subprocess.run(["git", "add", "."], cwd=REPO_PATH, check=True)

        status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=REPO_PATH
        )

        # Exit code 1 means there are staged changes.
        if status.returncode == 1:
            subprocess.run(
                ["git", "commit", "-m", "Saving login session changes to profile"],
                cwd=REPO_PATH,
                check=True
            )

            subprocess.run(
                ["git", "push", "origin", "dev-backend"],
                cwd=REPO_PATH,
                check=True
            )

            print(" New Profile has been pushed to git successfully!!!!!!!!!!!!!!!!!! ")
        else:
            logger.info("No changes to commit.")

    except subprocess.CalledProcessError:
        logger.exception("Git operation failed.")

def write_doctor_snapshot(doctor_id):
    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id)
    clinics_list = clinic_database_management.get_clinic_by_doctor_id(doctor_id)
    if isinstance(clinics_list, dict):
        clinics_list = [clinics_list]
    for clinic in clinics_list:
        clinic["clinic_address"] = dict_to_string(d=clinic["clinic_address"], fmt="vo")
        clinic["visit_schedule"] = dict_to_string(d=clinic["visit_schedule"], fmt="kv")
    filtered_list = [remove_bytes_from_dict(x) for x in clinics_list]
    doctor_data['clinics'] = filtered_list
    profile_pic_uri = doctor_data.get("profile_pic_uri")

    rendered = render_template(
        'doctor_profile_4.html',
        user_id=doctor_id,
        profile_pic_uri=profile_pic_uri,
        doctor_data=doctor_data,
        clinics=filtered_list,
        clinic_length=len(filtered_list)
    )

    os.makedirs(PROJECT_ROOT, exist_ok=True)
    with NamedTemporaryFile(mode="w", delete=False, dir=PROJECT_ROOT, suffix=".tmp", encoding="utf-8") as tmp:
        tmp.write(rendered)
        tmp_path = tmp.name
    os.replace(tmp_path, SNAPSHOT_PATH)
    gitsubprocess()

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
DATE_TODAY = datetime.now(IST).date()
# Loading API key for SMS OTP verification
base = Path(__file__).parent
secret_env = (base / ".env.secrets").resolve()
if secret_env.is_file():
    val = dotenv_values(secret_env)
    #load_dotenv(env_path)
    print(f"ROUTE LOG : Loading secret environment variables from: {secret_env}")
else:
    raise RuntimeError(f".env file not found: {secret_env}")

FAST2SMS_API_KEY = val.get("FAST2SMS_API_KEY")

week_year = get_iso_week( datetime.now(IST).date())
CURRENT_WEEK = week_year["week"]
CURRENT_YEAR = week_year["year"]
UPCOMING_WEEK = CURRENT_WEEK+1
print(f"ROUTE LOG:: Current week = {CURRENT_WEEK}, Upcoming week = {UPCOMING_WEEK}, Today = { datetime.now(IST).date()}------------------------------------------------------------------------------------------------------------")

@bp.route("/", methods=["GET"])
def doctor_login_page():
    # medicine_database_management.append_medicine_record() # TODO use once to ingest med list
    return render_template("doctor_login.html")

@bp.route("/doctor-login", methods=["POST"])
def api_doctor_login():
    
    data = request.get_json() or {}
    if len(data) == 0 : return jsonify(success=False, error="Empty request!! Contact ADMINISTRATOR!!"), 400
    
    #extracting login data
    identifier = (data.get("identifier") or "").strip()
    password = data.get("password") or ""
    remember = bool(data.get("remember"))

    # sanity check
    if not identifier or not password:
        return jsonify(success=False, error="missing_credentials"), 400

    try:
        res = doctor_database_management.authenticate_identifier(identifier, password)
        if not res.get("success"):
            # distinguish not found vs invalid credentials
            err = res.get("error", "invalid_credentials")
            return jsonify(success=False, error=err), 401

        user = res["user"]
        
        # Assigning session doctor_id
        session.clear()
        session["doctor_id"] = user["doctor_id"]
        
        # set a flag for "remember" if requested (requires configuring permanent_session_lifetime)
        if remember:
            session.permanent = True

        current_app.logger.info("Doctor %s logged in", session.get("doctor_id"))

        # rendering doctor profile to index.html
        write_doctor_snapshot(user["doctor_id"])
        
        return jsonify(success=True, user_id=user["doctor_id"], redirect=url_for('main.doc_dashboard', doctor_id=user["doctor_id"])), 200

    except Exception:
        current_app.logger.exception("Login error")
        return jsonify(success=False, error="internal_error"), 500

@bp.route("/doctor-register", methods=["GET"])
def doctor_registration_form():
    return render_template("doctor_registration.html")

@bp.route("/doctor-register", methods=["POST"])
def register_route():
    data = request.get_json() or {}
    try:
        rec = doctor_database_management.append_registration_record(data)
        # TODO: send verification email asynchronously
        return jsonify(success=True, doctor_id=rec["doctor_id"]), 201
    except ValueError as ve:
        return jsonify(success=False, error=str(ve)), 400
    except Exception as e:
        current_app.logger.exception("Failed to save registration")
        return jsonify(success=False, error="internal_error"), 500

@bp.route("/doctor-edit-profile/<doctor_id>/edit", methods=["GET"])
def doctor_edit_profile_form(doctor_id):
    # load from DB using your existing DB helper
    data = doctor_database_management.get_doctor_by_id(doctor_id)
    filtered = {k: v for k, v in data.items() if k not in {'doctor_qr_uri', 'image_data', 'profile_pic_uri'}}

    print(f"ROUTE LOG :: doctor-edit-profile GET method :: data received from frontend (printing doctor_qr_uri,image_data,profile_pic_uri avoided) -------------------------------{json.dumps(filtered)}")
    
    if not data:
        abort(404)

    if "profile_pic_uri" in data:
            profile_pic_uri = data["profile_pic_uri"]
    else:
        profile_pic_uri = None

    return render_template("doctor_edit_profile.html", doctor_data=data, profile_pic_uri=profile_pic_uri)

@bp.route("/doctor-edit-profile/", methods=["POST"])
def doctor_update_profile():
    data = request.get_json() or {}
    print(f"ROUTE LOG :: doctor-edit-profile POST method :: data received from frontend -------------------------------{json.dumps(data)}")
    try:
        response = doctor_database_management.update_doctor_profile(data)
        print(f"ROUTE LOG : Printing response from update profile from routes-------------------------------{json.dumps(response)}")
        # TODO: send verification email asynchronously
        if response["success"] :
            return jsonify(success=True,user_id=response.get("doctor_id"),message="Profile update successfull"), 201
        else: return jsonify(success=False,user_id=response.get("doctor_id"),message="Problem updating profile"), 201
    except ValueError as ve:
        return jsonify(success=False, error=str(ve)), 400
    except Exception as e:
        current_app.logger.exception("Failed to update doctor profile !! Contact Admin!!")
        return jsonify(success=False, error="internal_error"), 500

@bp.route("/doctor-forgot-password", methods=["GET"])
def doctor_forgot_password_page():
    return render_template("doctor_forgot_password.html")

@bp.route("/doctor-clinic-seeding", methods=["GET", "POST"])
def doctor_clinic_seed_form():
    if 'doctor_id' not in session:
        return redirect(url_for('main.doctor_login_page'))

    if request.method == "POST":
        doctor_id = session.get("doctor_id")
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error":"invalid json"}), 400

        clinic_name = data.get("clinicName")
        clinic_contact = data.get("clinicContact")
        clinic_contact_alternative = data.get("clinicContactAlt")
        clinic_fees = data.get("clinicFees")
        clinic_email = data.get("clinicemail")

        address = {
            "house_no": data.get("houseNo"),
            "street": data.get("street"),
            "post_office": data.get("postOffice"),
            "police_station": data.get("policeStation"),
            "city": data.get("city"),
            "pin_code": data.get("pinCode"),
            "state": data.get("state"),
            "country": data.get("country")
        }

        # schedule comes as object under "schedule"
        schedule = data.get("schedule")

        clinic_data = {
            "clinic_name": clinic_name,
            "clinic_contact": clinic_contact,
            "clinic_contact_alternative":clinic_contact_alternative,
            "clinic_email":clinic_email,
            "clinic_fees": clinic_fees,
            "clinic_address": address,
            "visit_schedule": schedule,
            "doctor_id":doctor_id,
        }

        # Save to DB
        response = clinic_database_management.append_clinic_registration_record(clinic_data)
        print(f"ROUTE LOG :: Inserted clinic: {response}")
        return jsonify(success=True,doctor_id=doctor_id,message="Clinic has been inserted successfully!!",redirect=True), 201

    username=session.get("doctor_id")
    #print("Printing username from add clinic................!!!!!!!!!!!")
    #print(username)
    doctor_data=doctor_database_management.get_doctor_by_id(doctor_id=username)
    return render_template(
        "doctor_add_clinic.html",
        username=username,
        doctor_data=doctor_data
    )

@bp.route("/clinic-booking", methods=["GET"])
def clinic_booking():

    clinic_id = request.args.get("clinic_id", "").strip()
    doctor_id = request.args.get("doctor_id", "").strip()

    if not clinic_id or not doctor_id : return jsonify({"error": "Arguments missing! Clinic ID or Doctor ID missing!!"}), 404
    
    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id=doctor_id)
    clinic_data = clinic_database_management.get_clinic_by_clinic_id(clinic_id=clinic_id)

    if not doctor_data or not clinic_data : return jsonify({"WARNING": "Clinic Data or Doctor Data missing!!"}), 404
    
    if "profile_pic_uri" in doctor_data:
            profile_pic_uri = doctor_data["profile_pic_uri"]
    else:
        profile_pic_uri = None

    clinic_address = dict_to_string(d=clinic_data["clinic_address"],fmt="vo")
    #visit_schedule = dict_to_string(d=clinic_data["visit_schedule"],fmt="kv")
    visit_schedule = dict_to_ordered_list(visits=clinic_data["visit_schedule"])
    print(f"Route LOG : Printing visit schedule : {visit_schedule}.............................................................")

    return render_template("clinic_booking.html",doctor_data=doctor_data,clinic_data=clinic_data,profile_pic_uri=profile_pic_uri,clinic_address=clinic_address,visit_schedule=visit_schedule) 

@bp.route("/send-otp", methods=["POST"]) #OTP verification added
def send_otp():
    data = request.get_json() or {}
    mobile = data.get("patient_mobile")
    print(f"ROUTE LOG : Received mobile number.......................{mobile}")
    if not mobile or not mobile.isdigit() or len(mobile) < 10:
        return jsonify({"error": "invalid_mobile"}), 400

    otp = str(random.randint(100000, 999999))
    session["booking_otp"] = otp
    session["booking_mobile"] = mobile

    url = "https://www.fast2sms.com/dev/bulkV2"
    full_number = "91" + mobile[-10:]  # ensure 10 digits + country code

    payload = {
        "route": "q",
        "message": f"OTP from Doctopal for your doctor appointment booking is {otp}",
        "numbers": full_number,
        "sms_details": "1"
    }

    headers = {
        "authorization": FAST2SMS_API_KEY,
        "accept": "application/json",
        "content-type": "application/json"
    }

    # send JSON body
    response = requests.post(url, json=payload, headers=headers, timeout=10)

    try:
        returned_msg = response.json()
    except ValueError:
        return jsonify({"error": "bad_response", "raw": response.text}), 502

    print(f"ROUTE LOG: fast2sms response {returned_msg}")

    success = returned_msg.get("return", False)
    status_code = 200 if success else returned_msg.get("status_code", 400)

    current_app.logger.info("Generated OTP for %s", mobile)
    return jsonify({"success": success, "otp": otp , "message": returned_msg}), status_code

@bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    otp = request.form.get("otp", "").strip()
    if not otp:
        return jsonify({"verified": False, "error": "missing_otp"}), 400
    if session.get("booking_otp") == otp:
        session.pop("booking_otp", None)
        session["otp_verified"] = True
        return jsonify({"verified": True}), 200
    return jsonify({"verified": False}), 400

@bp.route("/submit-booking", methods=["POST"])
def submit_booking():

    data = request.get_json() or {}
    print("ROUTE LOG : Printing data received from submit-booking handle.......................................")
    print(json.dumps(data))
    #return jsonify(success=True, doctor_id=data["doctor_id"]), 201
    try:
        rec = patient_database_management.append_patient_registration_record(data)
        #return
        # TODO: send verification email asynchronously
        return jsonify(success=True, serial_number=rec["serial_number"],uTAN=rec["uTAN"],visit_day=rec["visit_day"],visit_date=rec["visit_date"]), 201
    except ValueError as ve:
        return jsonify(success=False, error=str(ve)), 400
    except Exception as e:
        current_app.logger.exception("Failed to save patient booking")
        return jsonify(success=False, error="internal_error"), 500
    
@bp.route("/doctor-diagnose-patient", methods=["GET"])
def doctor_diagnose_patient():

    doctor_id = request.args.get("doctor_id", "").strip()

    if not doctor_id: return jsonify({"error": "Arguments missing! Doctor ID  missing!!"}), 404

    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id=doctor_id)
    
    return render_template("doctor_diagnose_patient.html",doctor_data=doctor_data) 

@bp.route("/patient-update-form", methods=["GET"])
def update_patient():

    doctor_id = request.args.get("doctor_id", "").strip()
    uTAN = request.args.get("uTAN", "").strip()
    print(f"ROUTE LOG :: Printing from /patient-update-form Doctor ID = {doctor_id}, uTAN = {uTAN}................")
    if not doctor_id or not uTAN: return jsonify({"error": "Arguments missing! Doctor ID or uTAN missing!!"}), 404

    patient = patient_database_management.get_patient_by_token_number(token_number=uTAN)
    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id=doctor_id)
    clinic_data = clinic_database_management.get_clinic_by_clinic_id(clinic_id=patient['clinic_id'])
    clinic_address = dict_to_string(d=clinic_data['clinic_address'])
    
    return render_template("update_patient.html",doctor_data=doctor_data,patient=patient,clinic_data=clinic_data,clinic_address=clinic_address) 

@bp.route("/new-patient-form", methods=["GET"])
def new_patient():

    doctor_id = request.args.get("doctor_id", "").strip()
    clinic_id = request.args.get("clinic_id", "").strip()
    print(f"ROUTE LOG :: Printing from /new-patient-form Doctor ID = {doctor_id}, clinic_id = {clinic_id}................")
    if not doctor_id or not clinic_id: return jsonify({"error": "Arguments missing! Doctor ID or uTAN missing!!"}), 404

    patient = {}
    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id=doctor_id)
    clinic_data = clinic_database_management.get_clinic_by_clinic_id(clinic_id=clinic_id)
    clinic_address = dict_to_string(d=clinic_data['clinic_address'])
    
    return render_template("update_patient.html",doctor_data=doctor_data,patient=patient,clinic_data=clinic_data,clinic_address=clinic_address) 


@bp.route("/download_placard/<doctor_id>/<clinic_id>")
def download_placard(doctor_id, clinic_id):

    doctor = doctor_database_management.get_doctor_by_id(doctor_id)
    clinic = clinic_database_management.get_clinic_by_clinic_id(clinic_id)


    return render_template(
        "placard.html",
        doctor_data=doctor,
        clinic_data=clinic,
        visit_schedule = dict_to_string(clinic['visit_schedule'],fmt="kv"),
        clinic_address=dict_to_string(clinic['clinic_address'])
    )

@bp.route("/patient-generate-prescription", methods=["POST"])
def generate_prescription_patient():

    data = request.get_json() or {}
    
    print(f"ROUTE LOG :: Printing from /patient-update-form patient_data = {json.dumps(data)}................")
    if not data : return jsonify({"error": "Arguments missing! Patient data missing!! Unable to generate prescription"}), 404
    
    update_response = patient_database_management.update_patient_profile(data=data)
    print(f"ROUTE LOG :: Printing response generate_prescription_patient {update_response}")
    if not update_response['success'] : return jsonify({"error": "update unsuccessfull! Patient data not entered in db!! Unable to generate prescription"}), 404

    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id=data["doctor_id"])
    clinic_data = clinic_database_management.get_clinic_by_clinic_id(clinic_id=data["clinic_id"])
    visit_schedule = dict_to_string(d=clinic_data["visit_schedule"],fmt="kv")
    clinic_address = dict_to_string(d=clinic_data["clinic_address"],fmt="vo")

    clinics_list = clinic_database_management.get_clinic_by_doctor_id(data["doctor_id"])
    if isinstance(clinics_list, dict):
        clinics_list = [clinics_list]

    clinics_list_processed = []
    for clinic in clinics_list:
        doctor_affiliation = extract_doctor_affiliations(clinic)
        clinics_list_processed.append(doctor_affiliation)
    
    print(f"ROUTE LOG : Printing from /patient-generate-prescription generated schedule : {visit_schedule} . address : {clinic_address}, doctor_affiliation : {clinics_list_processed}")
    html = render_template("doctor_prescription.html",patient_data=data,doctor_data=doctor_data,clinic_data=clinic_data,visit_schedule=visit_schedule,clinic_address=clinic_address,prescription_date=str( datetime.now(IST).date()),doctor_affiliation=clinics_list_processed) 

    return jsonify({
        'status': 'ok',
        'patient_prescription_html': html,
    }), 200

# Redundant endpoint
@bp.route("/doctor-profile", methods=["GET"])
def doctor_profile():
    doctor_id = request.args.get("doctor_id", "").strip()
    if not doctor_id:
        return redirect(url_for('main.doctor_login_page'))

    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id)
    clinics_list = clinic_database_management.get_clinic_by_doctor_id(doctor_id)
    if isinstance(clinics_list, dict):
        clinics_list = [clinics_list]
    for clinic in clinics_list:
        clinic["clinic_address"] = dict_to_string(d=clinic["clinic_address"], fmt="vo")
        clinic["visit_schedule"] = dict_to_string(d=clinic["visit_schedule"], fmt="kv")
    filtered_list = [remove_bytes_from_dict(x) for x in clinics_list]
    doctor_data['clinics'] = filtered_list
    profile_pic_uri = doctor_data.get("profile_pic_uri")

    rendered = render_template(
        'doctor_profile_4.html',
        user_id=doctor_id,
        profile_pic_uri=profile_pic_uri,
        doctor_data=doctor_data,
        clinics=filtered_list,
        clinic_length=len(filtered_list)
    )

    # atomic write to project root
    os.makedirs(PROJECT_ROOT, exist_ok=True)
    tmp_path = None
    with NamedTemporaryFile(mode="w", delete=False, dir=PROJECT_ROOT, suffix=".tmp", encoding="utf-8") as tmp:
        tmp.write(rendered)
        tmp_path = tmp.name
    os.replace(tmp_path, SNAPSHOT_PATH)  # atomic replace

    # Serve the written file
    return send_file(SNAPSHOT_PATH)

@bp.route('/doc_dashboard/<doctor_id>', methods=["GET"])
def doc_dashboard(doctor_id):
    if not doctor_id:
        return redirect(url_for('main.doctor_login_page'))
    
    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id)
    clinics_list = clinic_database_management.get_clinic_by_doctor_id(doctor_id)
    print(f"ROUTE LOG : Printing doctor_id from doctor dashboard route::list type = {doctor_id}")

    if isinstance(clinics_list, dict):
        clinics_list = [clinics_list]

    #Converting schedules for ease of display
    for clinic in clinics_list:
        clinic["clinic_address"] = dict_to_string(d=clinic["clinic_address"],fmt="vo")
        clinic["visit_schedule"] = dict_to_string(d=clinic["visit_schedule"],fmt="kv")

    
    filtered_list = [remove_bytes_from_dict(x) for x in clinics_list ]
    print(f"ROUTE LOG : Clinic list found for doctor dashboard::list type = {type(filtered_list)} ::: length = {len(filtered_list)}")
    doctor_data['clinics'] = filtered_list

    if "profile_pic_uri" in doctor_data:
        profile_pic_uri = doctor_data["profile_pic_uri"]
    else:
        profile_pic_uri = None
    
    appointments_upcoming_week = patient_database_management.get_patient_count_for_week(doctor_id=doctor_id,week=str(UPCOMING_WEEK))
    appointments_today = patient_database_management.get_patient_count_for_visit_date(doctor_id=doctor_id,date=str( datetime.now(IST).date()))
    appointments_current_week = patient_database_management.get_patient_count_for_week(doctor_id=doctor_id,week=str(CURRENT_WEEK))

    return render_template(
        'doctor_dashboard.html',
        user_id=doctor_id,
        profile_pic_uri=profile_pic_uri,
        doctor_data=doctor_data,
        clinics = filtered_list,
        clinic_length = len(filtered_list),
        appointments_upcoming_week = appointments_upcoming_week,
        appointments_today = appointments_today,
        appointments_current_week = appointments_current_week
    )

@bp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()  # Clear the session
    return redirect(url_for('main.doctor_login_page'))  # Redirect to login page

@bp.route('/doc_clinic_update/<doctor_id>/<clinic_id>', methods=["GET"])
def doc_clinic_update(doctor_id:str,clinic_id:str):
    if not doctor_id or not clinic_id:
        return redirect(url_for('main.doctor_login_page'))
    
    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id)
    clinic = clinic_database_management.get_clinic_by_clinic_id(clinic_id)

    # Serializing visit schedult to be rendered at client side............
    vs = clinic.get('visit_schedule') or {}
    schedule_array = []
    for day, ranges in vs.items():
        for r in ranges:
            if '-' in r:
                start, end = r.split('-', 1)
                schedule_array.append({"day": day, "start": start, "end": end})
    visit_schedule_serialized = schedule_array  # pass this to template
    print(f"ROUTE LOG : Printing serialized visit schedule for client side rendering :::::: {visit_schedule_serialized}")

    return render_template(
        'doctor_clinic_update.html',
        user_id = doctor_id,
        doctor_data = doctor_data,
        clinic = clinic,
        visit_schedule_serialized = visit_schedule_serialized
    )

@bp.route('/doc_clinic_update/<doctor_id>/<clinic_id>', methods=["POST"])
def doc_clinic_update_post(doctor_id:str,clinic_id:str):

    print(f"ROUTE LOG : Enterinng clinic data update post method !!")
    data = request.get_json() or {}
    print(f"ROUTE LOG : Printing data received servers side at UPDATE CLINIC for doc = {doctor_id} , clinic = {clinic_id} -------------------------------{json.dumps(data)}")
    try:
        response = clinic_database_management.update_clinic_profile(data)
        print(f"ROUTE LOG : Printing response from update profile from routes-------------------------------{json.dumps(response)}")
        # TODO: send verification email asynchronously
        if response["success"] :
            return jsonify(success=True,user_id=doctor_id,message="Clinic update successfull"), 201
        else: return jsonify(success=False,user_id=doctor_id,message="Problem updating Clinic profile"), 201
    except ValueError as ve:
        return jsonify(success=False, error=str(ve)), 400
    except Exception as e:
        current_app.logger.exception("Failed to update Clinic profile !! Contact Admin!!")
        return jsonify(success=False, error="internal_error"), 500

@bp.route('/doc_delete_clinic/<doctor_id>/<clinic_id>', methods=["GET"])
def doc_clinic_delete(doctor_id:str,clinic_id:str):
    if not doctor_id or not clinic_id:
        return redirect(url_for('main.doctor_login_page'))
    
    response = clinic_database_management.remove_clinic_by_doc_clin_id(clinic_id=clinic_id,doctor_id=doctor_id)
    
    if response.acknowledged :
        print(f"ROUTE LOG :: Clinic removal successful. Delete Count {response.deleted_count} ")
    else:
        print(f"ROUTE LOG :: Clinic removal unsuccessful. SERVER RESPONSE !! => {response} ")
    
    return redirect(url_for('main.doc_dashboard', doctor_id=doctor_id))
    
@bp.route('/clinic_dashboard/<doctor_id>/<clinic_id>', methods=["GET"])
def doc_clinic_dashboard(doctor_id:str,clinic_id:str):
    
    doctor_data = doctor_database_management.get_doctor_by_id(doctor_id)
    clinic_data = clinic_database_management.get_clinic_by_clinic_id(clinic_id)
    clinic_address = dict_to_string(d=clinic_data["clinic_address"],fmt="vo")
    visit_schedule = dict_to_string(d=clinic_data["visit_schedule"],fmt="kv")
    patient_list = patient_database_management.get_patient_by_doctor_id_clinic_id(doctor_id=doctor_id,clinic_id=clinic_id)
    previous_appointments, appointments_today, upcoming_appointments = count_patients_by_timeframe(patient_list=patient_list)
    
    return render_template(
        'clinic_dashboard.html',
        doctor_data = doctor_data,
        clinic_data = clinic_data,
        clinic_address = clinic_address,
        visit_schedule = visit_schedule,
        patient_list = patient_list,
        previous_appointments=previous_appointments,
        appointments_today=appointments_today,
        upcoming_appointments=upcoming_appointments
    )

@bp.route("/search_meds")
def search_meds():
    db = medicine_database_management.med_db
    collection = db.collection

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    results = []

    # 1. Exact name match first
    cursor = collection.find({"name": {"$regex": f"^{q}$", "$options": "i"}},
                             {"name": 1, "salt_composition": 1, "brand": 1}).limit(50)
    results = list(cursor)

    # 2. If no exact name match, try partial name match
    if not results:
        cursor = collection.find({"name": {"$regex": q, "$options": "i"}},
                                 {"name": 1, "salt_composition": 1, "brand": 1}).limit(50)
        results = list(cursor)

    # 3. If still nothing, try salt composition
    if not results:
        cursor = collection.find({"salt_composition": {"$regex": q, "$options": "i"}},
                                 {"name": 1, "salt_composition": 1, "brand": 1}).limit(50)
        results = list(cursor)

    # 4. Finally, try brand
    if not results:
        cursor = collection.find({"brand": {"$regex": q, "$options": "i"}},
                                 {"name": 1, "salt_composition": 1, "brand": 1}).limit(50)
        results = list(cursor)

    # Format results
    formatted = []
    for d in results:
        formatted.append({
            "id": str(d.get("_id")),
            "name": d.get("name"),
            "salt_composition": d.get("salt_composition"),
            "brand": d.get("brand")
        })

    return jsonify(formatted)

#-------------------------------- >  Helper functions  < ---------------------------------------------------

def dict_to_string(d: dict, fmt: str = "vo") -> str:
    # ""
    #Convert dict to string.
    #fmt="kv" -> "KEY1 , Val1 . KEY2 , Val2" (key value pair, in insertion order)
    #fmt="vo" -> "Val1,Val2,Val3"  (values only, in insertion order)
    # ""
    if not isinstance(d, dict):
        raise TypeError("d must be a dict")

    day_names = {
        "mon": "Monday",
        "tue": "Tuesday",
        "wed": "Wednesday",
        "thu": "Thursday",
        "fri": "Friday",
        "sat": "Saturday",
        "sun": "Sunday"
    }

    if fmt == "kv":
        parts = [f"{day_names.get(k, k)} : {v[0]}" for k, v in d.items()]
        return " \n ".join(parts)
    elif fmt == "vo":
        vals = [str(v) for v in d.values()]
        return ", ".join(vals)
    else:
        raise ValueError("fmt must be 'kv' or 'vo'")


def remove_bytes_from_dict(d: dict) -> dict:
    return {k: v for k, v in d.items() if not isinstance(v, bytes)}

# convert functions for visit schedule
WEEK_ORDER = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

def dict_to_ordered_list(visits: dict, order=WEEK_ORDER):
    """
    visits: e.g. {'mon': ['08:00-14:00'], 'thu': ['08:00-14:00']}
    returns list like:
    [{'name':'Monday','time':'(08:00-14:00)'}, ...] including only days present, in `order`.
    """
    # normalize keys to full weekday names
    key_map = {
        "mon":"Monday","monday":"Monday",
        "tue":"Tuesday","tues":"Tuesday","tuesday":"Tuesday",
        "wed":"Wednesday","wednesday":"Wednesday",
        "thu":"Thursday","thurs":"Thursday","thursday":"Thursday",
        "fri":"Friday","friday":"Friday",
        "sat":"Saturday","saturday":"Saturday",
        "sun":"Sunday","sunday":"Sunday"
    }
    out = []
    for day in order:
        # find any visit entry that maps to this full name
        for k,v in visits.items():
            if key_map.get(k.strip().lower()) == day:
                times = v or []
                if not times:
                    continue
                time_str = ", ".join(times)
                out.append({"name": day, "time": f"({time_str})"})
                break
    return out

def ordered_list_to_dict(schedule_list: list):
    """
    schedule_list: [{'name':'Saturday','time':'(01:30pm - 04:00pm)'}, ...]
    returns dict like: {'saturday': ['01:30pm - 04:00pm'], ...} (lowercase keys)
    """
    out = {}
    for item in schedule_list:
        name = item.get("name","").strip()
        time_field = item.get("time","").strip()
        # strip surrounding parentheses if present
        if time_field.startswith("(") and time_field.endswith(")"):
            time_field = time_field[1:-1].strip()
        # split by comma if multiple times
        times = [t.strip() for t in time_field.split(",") if t.strip()]
        if times:
            out[name.lower()] = times
    return out

def extract_doctor_affiliations(rec):
    # rec may be dict from Mongo; normalize keys and nested clinic_address
    addr = rec.get("clinic_address", {}) or {}
    temp = {"post_office": addr.get("post_office") or "",
        "police_station": addr.get("police_station") or "",
        "city": addr.get("city") or "",
        "pincode": addr.get("pin_code") or addr.get("pin_code") or ""}
    str_address = dict_to_string(d=temp)
    return {
        "clinic_name": rec.get("clinicname") or "",
        "address": str_address 
    }

def count_patients_by_timeframe(patient_list: list): 
    """
    Returns counts of checked-in patients: today, before today, after today.
    Expects patient['visit_date'] in 'YYYY-MM-DD' (or ISO-parsable) and patient['checked_in'] boolean.
    """
    today = date.today()
    counts = {"today": 0, "before": 0, "after": 0}

    for p in patient_list:
        if not p.get("checked_in"):
            continue
        vd = p.get("visit_date")
        if not vd:
            continue
        # parse date robustly
        try:
            # prefer YYYY-MM-DD
            visit_dt = datetime.fromisoformat(vd).date()
        except Exception:
            try:
                visit_dt = datetime.strptime(vd, "%d.%m.%Y").date()
            except Exception:
                try:
                    visit_dt = datetime.strptime(vd, "%Y/%m/%d").date()
                except Exception:
                    continue  # skip if unparseable

        if visit_dt == today:
            counts["today"] += 1
        elif visit_dt < today:
            counts["before"] += 1
        else:
            counts["after"] += 1

    print(f"ROUTE LOG :: Patient Counts before : {counts["before"]} , today : {counts["today"]} , after : {counts["after"]} ")
    return counts["before"],counts["today"],counts["after"]

#-------------------------------------------------- END ----------------------------------------------------------------------