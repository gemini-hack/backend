"""add_missing_hiv_profile_columns

Revision ID: bc3f1a896da0
Revises: 3c6d8bc5a36c
Create Date: 2026-01-29 12:54:15.836536

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bc3f1a896da0'
down_revision: Union[str, Sequence[str], None] = '3c6d8bc5a36c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Define ENUM types
enrollmentsetting = postgresql.ENUM('OPD', 'TB_CLINIC', 'WARD', 'VCT', 'OUTREACH', 'PMTCT', 'OTHER', name='enrollmentsetting', create_type=False)
regimenline = postgresql.ENUM('FIRST_LINE', 'SECOND_LINE', 'THIRD_LINE', 'SALVAGE', name='regimenline', create_type=False)
whostage = postgresql.ENUM('STAGE_I', 'STAGE_II', 'STAGE_III', 'STAGE_IV', name='whostage', create_type=False)
functionalstatus = postgresql.ENUM('WORKING', 'AMBULATORY', 'BEDRIDDEN', name='functionalstatus', create_type=False)


def upgrade() -> None:
    """Upgrade schema - add missing HIV profile columns."""
    # Create ENUM types first
    enrollmentsetting.create(op.get_bind(), checkfirst=True)
    regimenline.create(op.get_bind(), checkfirst=True)
    whostage.create(op.get_bind(), checkfirst=True)
    functionalstatus.create(op.get_bind(), checkfirst=True)
    
    # Add columns to hiv_profiles
    op.add_column('hiv_profiles', sa.Column('enrollment_setting', enrollmentsetting, nullable=True))
    op.add_column('hiv_profiles', sa.Column('regimen_line', regimenline, nullable=True))
    op.add_column('hiv_profiles', sa.Column('who_clinical_stage', whostage, nullable=True))
    op.add_column('hiv_profiles', sa.Column('functional_status', functionalstatus, nullable=True))


def downgrade() -> None:
    """Downgrade schema - remove HIV profile columns."""
    op.drop_column('hiv_profiles', 'functional_status')
    op.drop_column('hiv_profiles', 'who_clinical_stage')
    op.drop_column('hiv_profiles', 'regimen_line')
    op.drop_column('hiv_profiles', 'enrollment_setting')
    
    # Drop ENUM types
    functionalstatus.drop(op.get_bind(), checkfirst=True)
    whostage.drop(op.get_bind(), checkfirst=True)
    regimenline.drop(op.get_bind(), checkfirst=True)
    enrollmentsetting.drop(op.get_bind(), checkfirst=True)

