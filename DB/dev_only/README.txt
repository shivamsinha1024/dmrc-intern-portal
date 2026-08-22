LOCAL DEVELOPMENT UTILITIES -- DO NOT RUN ON A DEPLOYED SERVER
==============================================================================

These scripts exist to reset and re-seed a developer's local database. None of
them is part of deployment. Two of them destroy data and one inserts people who
do not exist.

  factory_reset.sql
      Empties the database back to a fresh state. DESTROYS ALL DATA.

  reset_application_data.sql
      Clears applications and candidates while leaving configuration in place.
      DESTROYS CANDIDATE DATA.

  seed_dev_data.sql
      Inserts FICTITIOUS employees, users and applications for local testing.

      Note especially: on a newly created production database the employees and
      users tables are empty by design, and the portal correctly refuses every
      request until DMRC's real employee directory is loaded. This file will
      appear to fix that. It does not -- it populates the system with invented
      staff, and any referral filed afterwards is attributed to a person who
      does not work at DMRC.

  fix_employee_names.sql
      A one-off correction applied to a development dataset.

To populate a production database, see steps 5 and 6 of the deployment
instructions in the project README.
==============================================================================
