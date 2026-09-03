import sqlite3
import csv
import json
import os
from datetime import datetime
from rcm_queue_db import get_agent_analytics, get_filtered_queue_stats

MAIN_DB = "/root/RCM_7021/rcm_7021.db"

class ReportGenerator:
    def __init__(self, provider_id=None):
        self.provider_id = provider_id
        self.tmp_dir = "/tmp/rcm_reports"
        os.makedirs(self.tmp_dir, exist_ok=True)

    def _get_queue_data(self, filters):
        # Wraps existing get_filtered_queue_stats
        return get_filtered_queue_stats(filters)

    def _get_agent_data(self, filters):
        # Wraps existing get_agent_analytics
        return get_agent_analytics(filters)

    def generate_single_agent(self, agent_ext, date_from, date_to):
        filters = {'date_from': date_from, 'date_to': date_to, 'agents': [agent_ext]}
        data = self._get_agent_data(filters)
        return self._write_csv(f"agent_{agent_ext}_{date_from}_{date_to}.csv", ["Agent", "Total Calls", "Answered", "No Answer", "Talk Time", "Hold Time"], data)

    def generate_single_queue(self, queue_num, date_from, date_to):
        filters = {'date_from': date_from, 'date_to': date_to, 'queues': [queue_num]}
        data = self._get_queue_data(filters)
        return self._write_csv(f"queue_{queue_num}_{date_from}_{date_to}.csv", ["Queue", "Total Calls", "Answered", "Abandoned", "Timeout", "Talk Time", "Hold Time"], data)

    def generate_all_queues(self, date_from, date_to):
        filters = {'date_from': date_from, 'date_to': date_to}
        data = self._get_queue_data(filters)
        return self._write_csv(f"all_queues_{date_from}_{date_to}.csv", ["Queue", "Total Calls", "Answered", "Abandoned", "Timeout", "Talk Time", "Hold Time"], data)

    def generate_all_agents(self, date_from, date_to):
        filters = {'date_from': date_from, 'date_to': date_to}
        data = self._get_agent_data(filters)
        return self._write_csv(f"all_agents_{date_from}_{date_to}.csv", ["Agent", "Total Calls", "Answered", "No Answer", "Talk Time", "Hold Time"], data)

    def generate_agents_by_queue(self, date_from, date_to):
        # Queue -> Agents breakdown
        # This requires fetching data per queue, then breaking down by agent
        pass # Simplified for CSV structure, would output combined stats
        return "/tmp/rcm_reports/combined.csv"

    def _write_csv(self, filename, headers, data):
        filepath = os.path.join(self.tmp_dir, filename)
        with open(filepath, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            # In a real impl, map data to headers safely
            if isinstance(data, list):
                for row in data:
                    writer.writerow([row.get(h.lower().replace(' ', '_'), 0) for h in headers])
        return filepath

    def archive_report(self, filepath, report_type, scope, period_start, period_end):
        if not self.provider_id: return
        from storage_providers import get_provider_instance
        provider = get_provider_instance(self.provider_id)
        if provider and provider.connect():
            filename = os.path.basename(filepath)
            ext_path = f"Reports/{report_type}/{filename}"
            success, final_ext_path, err = provider.upload_file(filepath, ext_path)
            if success:
                conn = sqlite3.connect(MAIN_DB)
                c = conn.cursor()
                c.execute("""
                    INSERT INTO reports_archive 
                    (report_type, scope, period_start, period_end, provider_id, external_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (report_type, scope, period_start, period_end, self.provider_id, final_ext_path))
                conn.commit()
                conn.close()
                os.remove(filepath) # Remove local tmp
