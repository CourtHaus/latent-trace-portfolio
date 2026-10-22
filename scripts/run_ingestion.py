"""Compatibility script for invoking the CaseSignal ETL pipeline.

This file exists for contributors who prefer running a repository-local script
instead of the installed `casesignal-etl` console command.
"""

from casesignal.etl.runners.run_pipeline import main

if __name__ == "__main__":
    main()
