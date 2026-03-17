# School Facility Data

## Square footage per child

To compute **sq ft per child** for Elementary, Middle, and High:

1. **Add square footage** to `level_sqft.csv`:
   - Get total building square footage for each level from:
     - District Long Range Facility Plan
     - Capital planning documents
     - NJ DOE [Educational Facilities](https://www.nj.gov/education/facilities/)
     - District business office

2. **Run the script**:
   ```bash
   python code/analysis/sqft_per_child.py
   ```

3. **Output**: `sqft_per_child.csv` with enrollment (from AMR), total sq ft, and sq ft per child for each level.

Enrollment is extracted from the AMR Schedule of Audited Enrollments (K–12 regular education by grade).
