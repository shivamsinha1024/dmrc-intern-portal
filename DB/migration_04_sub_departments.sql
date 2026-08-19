-- =============================================================================
-- DMRC INTERNSHIP PORTAL
-- MIGRATION 04 : SUB-DEPARTMENT LIST
-- Target: TiDB Cloud (also valid on MySQL 8.0+)
-- =============================================================================
--
-- WHAT THIS DOES
-- --------------
-- Replaces the placeholder sub-department list with the official designations
-- supplied by DMRC HR.
--
-- The previous list held descriptive names -- TRACTION, AFC, ROLLING STOCK --
-- which were stand-ins. The real units are identified by post designation, and
-- their capitalisation and punctuation are part of the name: "GM/HR/O&M",
-- "ED/S&T/R&D", "CPM-2,3,4,5,6".
--
-- STORED IN UPPER CASE, like every other field in this portal. That is a
-- deliberate data rule, not a styling choice: upper case removes ambiguity
-- between similar-looking characters and keeps entries legible on a crowded
-- screen. Email addresses are the only exception anywhere in the system.
--
-- The punctuation IS part of the name and is preserved exactly: the slashes in
-- GM/HR/O&M, the ampersands in GM/E&M and ED/S&T/R&D, and the commas and hyphen
-- in CPM-2,3,4,5,6.
--
-- BEFORE YOU RUN IT
-- -----------------
-- The old rows are DELETED. That is only safe while nothing refers to them:
--
--     cycle_sub_departments   -- which units a cycle offers (ON DELETE CASCADE)
--     joining_details         -- the unit a candidate was posted to (NO CASCADE)
--
-- The second has no cascade, so if ANY application has been allotted a
-- sub-department, the delete will fail and this migration will stop with a
-- foreign key error. Nothing will have changed.
--
-- Section 1 reports what is referring to them. If it returns anything other
-- than zeros, STOP -- either archive those cycles first, or ask for a variant
-- of this script that renames in place instead of replacing.
--
-- Immediately after a factory reset, both are empty and this is safe.
-- =============================================================================

USE dmrc_internship_portal;


-- -----------------------------------------------------------------------------
-- 1. PRE-FLIGHT -- both columns must read 0 before continuing.
-- -----------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM cycle_sub_departments) AS cycle_mappings,
  (SELECT COUNT(*) FROM joining_details WHERE allotted_sub_department_id IS NOT NULL)
                                               AS allotted_to_candidates;


-- -----------------------------------------------------------------------------
-- 2. REPLACE THE LIST
--
-- The cycle mappings are cleared first. Every cycle chooses which units it
-- offers, and those choices referred to the old rows -- they cannot survive a
-- change of list, and leaving them would map cycles to units that no longer
-- exist. A SYS-ADMIN re-selects the units for each cycle afterwards.
-- -----------------------------------------------------------------------------
DELETE FROM cycle_sub_departments;
DELETE FROM sub_departments;
ALTER TABLE sub_departments AUTO_INCREMENT = 1;

-- Fifteen units, in the order supplied by HR. is_global_active defaults to TRUE:
-- the unit exists organisation-wide. Whether a given CYCLE offers it is a
-- separate, per-cycle decision made in the Admin Control Center.
INSERT INTO sub_departments (sub_department_name) VALUES
('GM/LEGAL'),
('GM/PB'),
('GM/FINANCE'),
('CGM/TRACTION'),
('ED/FINANCE'),
('GM/HR/O&M'),
('AGM/HR/P'),
('CPM-2,3,4,5,6'),
('GM/E&M'),
('GM/SIGNALLING'),
('GM/TELECOM'),
('ED/S&T/R&D'),
('ED/IT'),
('ED/RS/O&M'),
('GM/OPERATIONS');


-- -----------------------------------------------------------------------------
-- 2b. DEPARTMENTS -- same rule
--
-- Departments were seeded in mixed case ('Civil', 'Mechanical/RS') while every
-- screen displays them in capitals. Renamed rather than replaced: applications
-- reference departments by id, so a rename leaves every existing record intact.
-- -----------------------------------------------------------------------------
UPDATE departments SET department_name = UPPER(department_name);


-- -----------------------------------------------------------------------------
-- 2c. DOCUMENT TYPES -- same rule
--
-- Renamed rather than replaced: applications reference document types by id,
-- and every application's frozen requirements snapshot stores the name as TEXT.
-- Renaming leaves both intact. Existing snapshots keep whatever capitalisation
-- was current when they were taken, which is correct -- they are a record of
-- what a candidate was actually asked for.
-- -----------------------------------------------------------------------------
UPDATE document_types SET type_name = UPPER(type_name);


-- -----------------------------------------------------------------------------
-- 3. VERIFICATION -- runs automatically.
--
--   Expect exactly 15 rows, all active, in upper case with their punctuation
--   intact.
-- -----------------------------------------------------------------------------
SELECT sub_department_id, sub_department_name, is_global_active
FROM sub_departments
ORDER BY sub_department_id;

SELECT COUNT(*) AS total_units,
       SUM(CASE WHEN is_global_active THEN 1 ELSE 0 END) AS active_units
FROM sub_departments;

-- Departments and document types: all must now read in capitals.
SELECT department_id, department_name FROM departments ORDER BY department_id;
SELECT doc_type_id, type_name FROM document_types ORDER BY doc_type_id;
