/**
 * DMRC INTERN REFERRAL WIZARD — RELEASABLE APPS ENGINE
 * Powered natively by Alpine.js reactive state architecture.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('wizardEngine', () => ({
        // Interface View Layout State
        portalState: 'cycle_select', 
        showValidationWarning: false,

        // Navigation Controllers
        currentStep: 1,
        highestStepReached: 1,
        totalSteps: 5,
        
        // Identity & Synchronization Stamps
        applicationCode: 'DRAFT · NOT ISSUED',
        saveStatus: 'Not saved yet',

        // Final Submission State (Step 5)
        acceptedDeclarations: false,   // maps to applications.accepted_declarations
        showSubmitConfirm: false,      // confirm-before-lock modal
        finalTicket: null,             // simulated applications.application_code
        submittedAt: '',
        wasWaitlisted: false,          // snapshot of isWaitlisted at submit time
        reviewSections: { 1: true, 2: false, 3: false, 4: false },

        // TEMP: beforeunload guard handle. REMOVE once the Django backend
        // persists each step server-side (drafts will survive refresh then).
        unloadGuard: null,

        // SESSION MOCK (This will come from Django SSO later)
        sessionEmployee: {
            empId: 'EMP-4471',
            name: 'R. Sharma',
            designation: 'Senior Engineer',
            department: 'Signal & Telecom'
        },

        // Global Application State Matrix
        student: {
            fullName: '',
            fathersName: '',
            gender: '',
            dateOfBirth: '',
            mobile_number: '',
            personal_email: '',
            permanent_address: '',
            emergency_contact_name: '',
            emergency_contact_mobile: ''
        },

        academic: {
            university_name: '',
            college_name: '',
            course: '', 
            course_other: '',
            branch: '',
            branch_other: '',
            current_semester: '',
            grading_system: 'CGPA', 
            current_score: ''
        },

        documents: {
            aadhar: null,
            college_id: null,
            lor: null,
            photograph: null,
            signature: null
        },

        placement: {
            cycle_id: null, 
            sessionTerm: '',
            department_id: '',
            duration_weeks: '',
            requested_doj: '',
            is_ward: false
        },

        // --- DATA LISTS ---
        courseOptions: [
            'B.Tech / B.E.', 'M.Tech / M.E.', 'BCA', 'MCA', 'B.Sc', 'M.Sc',
            'BBA', 'MBA / PGDM', 'B.Com', 'M.Com', 'LLB', 'LLM', 'BA / MA', 'Diploma'
        ],

        branchOptions: [
            'Computer Science & Engineering', 'Information Technology',
            'Electronics & Communication', 'Electrical Engineering',
            'Mechanical Engineering', 'Civil Engineering',
            'Finance', 'Marketing', 'Human Resources', 'Operations',
            'Accounting', 'Commerce', 'Corporate Law', 'General Law',
            'Physics', 'Chemistry', 'Mathematics', 'General'
        ],

        // Labels used by the Step 5 review vault & hard validation gate
        documentLabels: {
            aadhar: 'AADHAR',
            college_id: 'College ID',
            lor: 'Letter of Recommendation',
            photograph: 'Passport Size Photograph',
            signature: 'Signature'
        },

        stepTitles: {
            1: 'Student Details',
            2: 'Academic Matrix',
            3: 'Document Vault',
            4: 'Internship Details'
        },

        // Sourced strictly from DB Section 7 (Seed Data)
        dmrcDepartments: [
            'Civil', 'Mechanical/RS', 'Electrical', 'IT', 
            'S&T', 'Finance', 'HR', 'Legal'
        ],

        // --- DYNAMIC DB MOCKS ---
        // Sourced from `cycle_joining_dates` table for the Flatpickr UI
        dbJoiningDates: [
            { cycle_id: 1, date: '2026-05-04' },
            { cycle_id: 1, date: '2026-05-11' },
            { cycle_id: 1, date: '2026-05-18' },
            { cycle_id: 1, date: '2026-05-25' },
            { cycle_id: 1, date: '2026-06-08' },
            { cycle_id: 1, date: '2026-06-22' },
            { cycle_id: 2, date: '2026-12-07' },
            { cycle_id: 2, date: '2026-12-14' },
            { cycle_id: 2, date: '2026-12-21' },
            { cycle_id: 2, date: '2026-12-28' },
            { cycle_id: 2, date: '2027-01-11' },
            { cycle_id: 2, date: '2027-01-25' }
        ],

        // Sourced from `cycle_department_capacities` table 
        // NOTE: IT is artificially forced to maximum capacity for UI testing.
        capacitySnapshot: {
            'Civil': { max: 25, occupied: 10 },
            'Mechanical/RS': { max: 25, occupied: 5 },
            'Electrical': { max: 40, occupied: 15 },
            'IT': { max: 25, occupied: 25 }, // FULL CAPACITY
            'S&T': { max: 40, occupied: 20 },
            'Finance': { max: 10, occupied: 2 },
            'HR': { max: 5, occupied: 1 },
            'Legal': { max: 5, occupied: 0 }
        },

        // --- DYNAMIC EVENT LISTENERS (RESTORED) ---
        get isWaitlisted() {
            if (!this.placement.department_id) return false;
            const cap = this.capacitySnapshot[this.placement.department_id];
            return cap ? (cap.occupied >= cap.max) : false;
        },

        initDOJCalendar(element) {
            const currentYear = new Date().getFullYear().toString();
            
            // Filters strictly by the selected cycle and isolates current year dates
            const allowedDates = this.dbJoiningDates
                .filter(d => d.cycle_id === this.placement.cycle_id && d.date.startsWith(currentYear))
                .map(d => d.date);

            flatpickr(element, { 
                dateFormat: 'Y-m-d', 
                altInput: true, 
                altFormat: 'd-m-Y',
                enable: allowedDates,
                minDate: "today" // Fix: Completely locks out any allowed date that has already passed
            });
        },

        // --- INPUT MASKING & VALIDATIONS ---
        restrictMobileInput(fieldPath, nextFieldId) {
            let clean = this.student[fieldPath].replace(/\D/g, '');
            if (clean.length > 10) clean = clean.substring(0, 10);
            this.student[fieldPath] = clean;

            if (clean.length === 10 && nextFieldId) {
                this.$nextTick(() => {
                    const nextEl = document.getElementById(nextFieldId);
                    if (nextEl) nextEl.focus();
                });
            }
        },

        isMobileInvalid(fieldPath) {
            const val = this.student[fieldPath];
            return val.length > 0 && val.length < 10;
        },

        restrictScoreInput() {
            let val = this.academic.current_score.replace(/[^0-9.]/g, '');
            const parts = val.split('.');
            if (parts.length > 2) {
                val = parts[0] + '.' + parts.slice(1).join('');
            }
            let num = parseFloat(val);
            if (!isNaN(num)) {
                if (this.academic.grading_system === 'CGPA' && num > 10) val = '10';
                if (this.academic.grading_system === 'Percentage' && num > 100) val = '100';
            }
            this.academic.current_score = val;
        },

        // --- FILE HANDLING LOGIC ---
        handleFileUpload(event, docType) {
            const file = event.target.files[0];
            
            if (!file) {
                this.documents[docType] = null;
                return;
            }

            const maxSize = 5 * 1024 * 1024;
            if (file.size > maxSize) {
                alert(`Upload failed: The file "${file.name}" exceeds the 5MB maximum limit.`);
                event.target.value = ''; 
                this.documents[docType] = null;
                return;
            }

            const validImageTypes = ['image/jpeg', 'image/png'];
            const validDocumentTypes = ['image/jpeg', 'image/png', 'application/pdf'];

            if (docType === 'photograph' || docType === 'signature') {
                if (!validImageTypes.includes(file.type)) {
                    alert("Invalid format: Photograph and Signature must be JPG or PNG images.");
                    event.target.value = '';
                    this.documents[docType] = null;
                    return;
                }
            } else {
                if (!validDocumentTypes.includes(file.type)) {
                    alert("Invalid format: Document must be PDF, JPG, or PNG.");
                    event.target.value = '';
                    this.documents[docType] = null;
                    return;
                }
            }

            this.documents[docType] = {
                file: file,
                name: file.name,
                previewUrl: URL.createObjectURL(file)
            };
            this.saveStatus = new Date().toLocaleTimeString();
        },

        previewDocument(docType) {
            const doc = this.documents[docType];
            if (doc && doc.previewUrl) {
                window.open(doc.previewUrl, '_blank');
            }
        },

        getUploadedCount() {
            return Object.values(this.documents).filter(doc => doc !== null).length;
        },

        // --- WORKFLOW CONTROLS ---
        confirmCycleSelection(cycleName, id) {
            this.placement.sessionTerm = cycleName;
            this.placement.cycle_id = id;
            this.applicationCode = `DMRC-2026${cycleName.substring(0,1).toUpperCase()}-PENDING`;
        },

        initializeWizard() {
            if (this.placement.cycle_id) {
                this.portalState = 'form_wizard';
                this.saveStatus = new Date().toLocaleTimeString();

                // TEMP: warn before refresh/close while the draft lives ONLY in
                // browser memory. REMOVE once the backend saves every step.
                this.unloadGuard = (e) => {
                    e.preventDefault();
                    e.returnValue = '';
                };
                window.addEventListener('beforeunload', this.unloadGuard);
            }
        },

        // --- UNIFIED VALIDATION ENGINE ---
        // Single source of truth for what is missing in a given step.
        // Used by BOTH the soft per-step warning and the Step 5 hard gate.
        // ALL fields are mandatory per HR policy.
        getStepMissing(step) {
            const missing = [];
            const blank = (v) => v === null || v === undefined || String(v).trim() === '';

            if (step === 1) {
                const bio = [
                    ['fullName', 'Full Name'],
                    ['fathersName', "Father's Name"],
                    ['gender', 'Gender'],
                    ['dateOfBirth', 'Date of Birth'],
                    ['mobile_number', 'Mobile Number'],
                    ['personal_email', 'Email ID'],
                    ['permanent_address', 'Permanent Address'],
                    ['emergency_contact_name', 'Emergency Contact Name'],
                    ['emergency_contact_mobile', 'Emergency Contact Mobile']
                ];
                for (const [field, label] of bio) {
                    if (blank(this.student[field])) missing.push(label);
                }
                if (this.student.mobile_number.length > 0 && this.student.mobile_number.length !== 10)
                    missing.push('Mobile Number (must be 10 digits)');
                if (this.student.emergency_contact_mobile.length > 0 && this.student.emergency_contact_mobile.length !== 10)
                    missing.push('Emergency Contact Mobile (must be 10 digits)');
            }
            else if (step === 2) {
                const acad = [
                    ['university_name', 'University Name'],
                    ['college_name', 'College / Institute Name'],
                    ['course', 'Course (Degree)'],
                    ['branch', 'Branch / Specialization'],
                    ['current_semester', 'Current Semester'],
                    ['current_score', 'Current Score']
                ];
                for (const [field, label] of acad) {
                    if (blank(this.academic[field])) missing.push(label);
                }
                if (this.academic.course === 'Other' && blank(this.academic.course_other))
                    missing.push('Custom Degree Name');
                if (this.academic.branch === 'Other' && blank(this.academic.branch_other))
                    missing.push('Custom Branch Name');
            }
            else if (step === 3) {
                for (const [key, label] of Object.entries(this.documentLabels)) {
                    if (!this.documents[key]) missing.push(label);
                }
            }
            else if (step === 4) {
                const place = [
                    ['department_id', 'Target Department'],
                    ['duration_weeks', 'Internship Duration'],
                    ['requested_doj', 'Preferred Date of Joining']
                ];
                for (const [field, label] of place) {
                    if (blank(this.placement[field])) missing.push(label);
                }
            }
            return missing;
        },

        validateCurrentStep() {
            return this.getStepMissing(this.currentStep).length === 0;
        },

        // --- STEP 5: HARD GATE + REVIEW HELPERS ---
        get missingByStep() {
            const groups = [];
            for (const step of [1, 2, 3, 4]) {
                const items = this.getStepMissing(step);
                if (items.length > 0) {
                    groups.push({ step: step, title: this.stepTitles[step], items: items });
                }
            }
            return groups;
        },

        get isReadyToSubmit() {
            return this.missingByStep.length === 0;
        },

        get canSubmit() {
            return this.isReadyToSubmit && this.acceptedDeclarations;
        },

        isSectionComplete(step) {
            return this.getStepMissing(step).length === 0;
        },

        toggleSection(n) {
            this.reviewSections[n] = !this.reviewSections[n];
        },

        setAllSections(open) {
            [1, 2, 3, 4].forEach(n => this.reviewSections[n] = open);
        },

        get allSectionsOpen() {
            return [1, 2, 3, 4].every(n => this.reviewSections[n]);
        },

        // --- DISPLAY FORMATTERS (review & success views) ---
        displayValue(v) {
            return (v === null || v === undefined || String(v).trim() === '') ? '—' : v;
        },

        displayDate(iso) {
            if (!iso) return '—';
            const [y, m, d] = iso.split('-');
            return `${d}-${m}-${y}`;
        },

        displayCourse() {
            return this.academic.course === 'Other' ? this.academic.course_other : this.academic.course;
        },

        displayBranch() {
            return this.academic.branch === 'Other' ? this.academic.branch_other : this.academic.branch;
        },

        displaySemester() {
            const s = this.academic.current_semester;
            if (!s) return '';
            return s === 'Graduated' ? 'Graduated / Alumni' : 'Semester ' + s;
        },

        displayScore() {
            if (!this.academic.current_score) return '';
            const unit = this.academic.grading_system === 'CGPA' ? ' CGPA (out of 10)' : '% (Percentage)';
            return this.academic.current_score + unit;
        },

        // --- FINAL SUBMISSION FLOW ---
        requestSubmit() {
            if (this.canSubmit) this.showSubmitConfirm = true;
        },

        submitApplication() {
            this.showSubmitConfirm = false;

            // ── SIMULATION (frontend-only phase) ─────────────────────────────
            // The real application_code is issued by the Django backend at
            // submission (unique per-cycle sequence from the DB). This 3-digit
            // sequence is DISPLAY-ONLY and must be replaced by the API response.
            const seq = String(Math.floor(Math.random() * 900) + 100);
            // ──────────────────────────────────────────────────────────────────

            const cycleLetter = this.placement.sessionTerm.substring(0, 1).toUpperCase();
            const wl = this.isWaitlisted ? 'WL-' : '';
            this.finalTicket = `DMRC-2026${cycleLetter}-${wl}${seq}`;

            this.applicationCode = this.finalTicket;
            this.wasWaitlisted = this.isWaitlisted;
            this.submittedAt = new Date().toLocaleString();
            // Backend later: status 'Draft' -> 'Submitted', stamp submitted_at,
            // set accepted_declarations = TRUE, is_waitlisted flag, insert
            // application_status_history row, queue 'Application Submitted' mail.

            // TEMP: draft no longer at risk once submitted; drop refresh guard.
            if (this.unloadGuard) {
                window.removeEventListener('beforeunload', this.unloadGuard);
                this.unloadGuard = null;
            }

            this.portalState = 'submitted';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        resetPortal() {
            // "Back to Dashboard": no dashboard exists yet, so restart the
            // portal cleanly. A reload guarantees pristine state and revokes
            // in-memory file previews. Replace with real navigation later.
            if (this.unloadGuard) {
                window.removeEventListener('beforeunload', this.unloadGuard);
                this.unloadGuard = null;
            }
            window.location.reload();
        },

        nextStep() {
            if (this.validateCurrentStep()) {
                this.proceedToNextStep();
            } else {
                this.showValidationWarning = true;
            }
        },

        proceedToNextStep() {
            this.showValidationWarning = false;
            if (this.currentStep < this.totalSteps) {
                this.currentStep++;
                if (this.currentStep > this.highestStepReached) {
                    this.highestStepReached = this.currentStep;
                }
                this.saveStatus = new Date().toLocaleTimeString();
            }
        },

        prevStep() {
            if (this.currentStep > 1) {
                this.currentStep--;
            }
        },

        goToStep(targetStep) {
            if (targetStep <= this.highestStepReached) {
                this.currentStep = targetStep;
            }
        }
    }));
});