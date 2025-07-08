# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import datetime
import argparse
from multiprocessing import Process

sys.path.append(str(os.environ['LSFMONITOR_INSTALL_PATH']) + '/monitor')
from common import common
from common import common_lsf
from common import common_sqlite3

# Import local config file if exists.
local_config_dir = str(os.environ['HOME']) + '/.lsfMonitor/conf'
local_config = str(local_config_dir) + '/config.py'

if os.path.exists(local_config):
    sys.path.append(local_config_dir)
    import config
else:
    from conf import config

os.environ['LSB_NTRIES'] = '3'
os.environ["PYTHONUNBUFFERED"] = '1'


def read_args():
    """
    Read arguments.
    """
    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--cleanup",
                        action="store_true",
                        default=False,
                        help='Clean up database with entries limiation.')
    parser.add_argument("-j", "--job",
                        action="store_true",
                        default=False,
                        help='Sample (finished) job info with command "bjobs -u all -d -UF".')
    parser.add_argument("-m", "--job_mem",
                        action="store_true",
                        default=False,
                        help='Sample (running) job memory usage information with command "bjobs -u all -r -UF".')
    parser.add_argument("-q", "--queue",
                        action="store_true",
                        default=False,
                        help='Sample queue info with command "bqueues".')
    parser.add_argument("-H", "--host",
                        action="store_true",
                        default=False,
                        help='Sample host info with command "bhosts".')
    parser.add_argument("-l", "--load",
                        action="store_true",
                        default=False,
                        help='Sample host load (ut/tmp/swp/mem) info with command "lsload".')
    parser.add_argument("-u", "--user",
                        action="store_true",
                        default=False,
                        help='Sample user (finished) job info with command "bjobs -u all -d -UF".')
    parser.add_argument("-U", "--utilization",
                        action="store_true",
                        default=False,
                        help='Sample utilization (slot/cpu/mem) info with command "lsload/bhosts/lshosts".')
    parser.add_argument("-UD", "--utilization_day",
                        action="store_true",
                        default=False,
                        help='Count and save utilization-day info with utilization data.')

    args = parser.parse_args()

    if (not args.cleanup) and (not args.job) and (not args.job_mem) and (not args.queue) and (not args.host) and (not args.load) and (not args.user) and (not args.utilization) and (not args.utilization_day):
        common.bprint('At least one argument of "cleanup/job/job_mem/queue/host/load/user/utilization/utilization_day" must be selected.', level='Error')
        sys.exit(1)

    return args.cleanup, args.job, args.job_mem, args.queue, args.host, args.load, args.user, args.utilization, args.utilization_day


class Sampling:
    """
    Sample LSF basic information with LSF bjobs/bqueues/bhosts/lshosts/lsload/busers commands.
    Save the infomation into sqlite3 DB.
    """
    def __init__(self, cleanup, job_sampling, job_mem_sampling, queue_sampling, host_sampling, load_sampling, user_sampling, utilization_sampling, utilization_day_sampling):
        self.cleanup = cleanup
        self.job_sampling = job_sampling
        self.job_mem_sampling = job_mem_sampling
        self.queue_sampling = queue_sampling
        self.host_sampling = host_sampling
        self.load_sampling = load_sampling
        self.user_sampling = user_sampling
        self.utilization_sampling = utilization_sampling
        self.utilization_day_sampling = utilization_day_sampling

        # Limitation on the number of sqlite database entries.
        self.db_entries_limit_dic = {'queue': 100000, 'host': 100000, 'load': 100000, 'utilization': 100000}

        # Get sample time.
        self.sample_second = int(time.time())
        self.sample_date = datetime.datetime.today().strftime('%Y%m%d')
        self.sample_time = datetime.datetime.today().strftime('%Y%m%d_%H%M%S')

        # Update self.db_path with cluster information.
        self.db_path = str(config.db_path) + '/monitor'
        (self.tool, cluster) = self.check_cluster_info()

        if cluster:
            self.db_path = str(config.db_path) + '/' + str(cluster)

        # Create db path.
        self.job_db_path = str(self.db_path) + '/job'
        self.job_mem_db_path = str(self.db_path) + '/job_mem'
        self.user_db_path = str(self.db_path) + '/user'

        self.create_dir(self.job_db_path)
        self.create_dir(self.job_mem_db_path)
        self.create_dir(self.user_db_path)

    def check_cluster_info(self):
        """
        Make sure LSF or Openlava environment exists.
        """
        (tool, tool_version, cluster, master) = common_lsf.get_lsid_info()

        if tool == '':
            common.bprint('Not find any LSF or Openlava environment!', date_format='%Y-%m-%d %H:%M:%S', level='Error')
            sys.exit(1)

        return tool, cluster

    def create_dir(self, dir_path):
        """
        Create dir_path with access permission 777.
        """
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path)
                os.chmod(dir_path, 0o777)
            except Exception as error:
                common.bprint('Failed on creating directory "' + str(dir_path) + '".', level='Error')
                common.bprint(error, color='red', display_method=1, indent=9)
                sys.exit(1)

    def cleanup_db(self):
        """
        Clean up sqlite3 database with self.db_entries_limit_dic limitation.
        """
        item_list = ['queue', 'host', 'load', 'utilization']

        for item in item_list:
            item_db_file = str(self.db_path) + '/' + str(item) + '.db'

            if os.path.exists(item_db_file):
                item_entries_limitation = self.db_entries_limit_dic[item]
                common.bprint('>>> Clean up "' + str(item_db_file) + '" with entries limitation ' + str(item_entries_limitation) + '...', date_format='%Y-%m-%d %H:%M:%S')
                (result, item_db_conn) = common_sqlite3.connect_db_file(item_db_file, mode='write')

                if result == 'passed':
                    item_table_list = common_sqlite3.get_sql_table_list(item_db_file, item_db_conn)

                    for item_table_name in item_table_list:
                        item_table_count = common_sqlite3.get_sql_table_count(item_db_file, item_db_conn, item_table_name)

                        if item_table_count != 'N/A':
                            if int(item_table_count) > item_entries_limitation:
                                begin_line = 0
                                end_line = int(item_table_count) - item_entries_limitation

                                common.bprint('Deleting database "' + str(item_db_file) + '" table "' + str(item_table_name) + '" ' + str(begin_line) + '-' + str(end_line) + ' lines to only keep ' + str(item_entries_limitation) + ' items.', date_format='%Y-%m-%d %H:%M:%S', level='Warning', indent=4)
                                common_sqlite3.delete_sql_table_rows(item_db_file, item_db_conn, item_table_name, 'sample_time', begin_line, end_line)

    def sample_job_info(self):
        """
        Sample (finished) job information.
        """
        common.bprint('>>> Sampling job info ...', date_format='%Y-%m-%d %H:%M:%S', )
        common.bprint('* Getting finished job information with command "bjobs -u all -d -UF" ...', date_format='%Y-%m-%d %H:%M:%S', indent=4)
        bjobs_dic = common_lsf.get_bjobs_uf_info('bjobs -u all -d -UF')

        # Re-organize jobs_dic with finished_date.
        date_bjobs_dic = {}

        for job in bjobs_dic.keys():
            finished_date = common_lsf.switch_bjobs_uf_time(bjobs_dic[job]['finished_time'], '%Y%m%d')

            if finished_date not in date_bjobs_dic:
                date_bjobs_dic[finished_date] = {}

            date_bjobs_dic[finished_date][job] = bjobs_dic[job]

        # Write db_file with finished_date.
        common.bprint('* Saving finished job information ...', date_format='%Y-%m-%d %H:%M:%S', indent=4)
        key_list = ['job', 'job_name', 'job_description', 'user', 'project', 'status', 'interactive_mode', 'queue', 'command', 'submitted_from', 'submitted_time', 'cwd', 'processors_requested', 'requested_resources', 'span_hosts', 'rusage_mem', 'started_on', 'started_time', 'finished_time', 'exit_code', 'term_signal', 'cpu_time', 'mem', 'swap', 'run_limit', 'pids', 'max_mem', 'avg_mem', 'pending_reasons', 'job_info']
        key_type_list = ['PRIMARY KEY', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT']
        key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

        for finished_date in date_bjobs_dic.keys():
            finished_date_db_file = str(self.job_db_path) + '/' + str(finished_date) + '.db'
            common.bprint('Writing ' + str(finished_date_db_file) + ' ...', date_format='%Y-%m-%d %H:%M:%S', indent=6)
            (result, finished_date_db_conn) = common_sqlite3.connect_db_file(finished_date_db_file, mode='write')

            if result == 'passed':
                common_sqlite3.create_sql_table(finished_date_db_file, finished_date_db_conn, 'job', key_string, commit=False)

                for job in date_bjobs_dic[finished_date].keys():
                    # Insert sql table value if not exists.
                    value_list = [job, date_bjobs_dic[finished_date][job]['job_name'], date_bjobs_dic[finished_date][job]['job_description'], date_bjobs_dic[finished_date][job]['user'], date_bjobs_dic[finished_date][job]['project'], date_bjobs_dic[finished_date][job]['status'], date_bjobs_dic[finished_date][job]['interactive_mode'], date_bjobs_dic[finished_date][job]['queue'], date_bjobs_dic[finished_date][job]['command'], date_bjobs_dic[finished_date][job]['submitted_from'], date_bjobs_dic[finished_date][job]['submitted_time'], date_bjobs_dic[finished_date][job]['cwd'], date_bjobs_dic[finished_date][job]['processors_requested'], date_bjobs_dic[finished_date][job]['requested_resources'], date_bjobs_dic[finished_date][job]['span_hosts'], date_bjobs_dic[finished_date][job]['rusage_mem'], date_bjobs_dic[finished_date][job]['started_on'], date_bjobs_dic[finished_date][job]['started_time'], date_bjobs_dic[finished_date][job]['finished_time'], date_bjobs_dic[finished_date][job]['exit_code'], date_bjobs_dic[finished_date][job]['term_signal'], date_bjobs_dic[finished_date][job]['cpu_time'], date_bjobs_dic[finished_date][job]['mem'], date_bjobs_dic[finished_date][job]['swap'], ' '.join(date_bjobs_dic[finished_date][job]['run_limit']), ' '.join(date_bjobs_dic[finished_date][job]['pids']), date_bjobs_dic[finished_date][job]['max_mem'], date_bjobs_dic[finished_date][job]['avg_mem'], ' '.join(date_bjobs_dic[finished_date][job]['pending_reasons']), date_bjobs_dic[finished_date][job]['job_info']]
                    value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                    common_sqlite3.insert_into_sql_table(finished_date_db_file, finished_date_db_conn, 'job', value_string, commit=False)

                finished_date_db_conn.commit()
                finished_date_db_conn.close()

        common.bprint('Done (' + str(len(bjobs_dic.keys())) + ' jobs).', date_format='%Y-%m-%d %H:%M:%S', indent=4)

    def sample_job_mem_info(self):
        """
        Sample (running) job memory usage information.
        """
        common.bprint('>>> Sampling job mem usage info ...', date_format='%Y-%m-%d %H:%M:%S')

        bjobs_dic = common_lsf.get_bjobs_uf_info('bjobs -u all -r -UF')
        job_list = list(bjobs_dic.keys())
        job_range_dic = common.get_job_range_dic(job_list)

        key_list = ['sample_second', 'sample_time', 'mem']
        key_type_list = ['INTEGER PRIMARY KEY', 'TEXT', 'TEXT']
        key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

        for job_range in job_range_dic.keys():
            job_mem_db_file = str(self.job_mem_db_path) + '/' + str(job_range) + '.db'
            (result, job_mem_db_conn) = common_sqlite3.connect_db_file(job_mem_db_file, mode='write')

            if result == 'passed':
                job_table_list = common_sqlite3.get_sql_table_list(job_mem_db_file, job_mem_db_conn)

                for job in job_range_dic[job_range]:
                    job_table_name = 'job_' + str(job)

                    # If job table (with old data) has been on the job_mem_db_file, cleanup it.
                    if job_table_name in job_table_list:
                        data_dic = common_sqlite3.get_sql_table_data(job_mem_db_file, job_mem_db_conn, job_table_name, ['sample_second'])

                        if data_dic:
                            if len(data_dic['sample_second']) > 0:
                                last_sample_second = int(data_dic['sample_second'][-1])

                                if self.sample_second - last_sample_second > 3600:
                                    common.bprint('Table "' + str(job_table_name) + '" already existed even one hour ago, will cleanup it.', date_format='%Y-%m-%d %H:%M:%S', level='Warning', indent=4)
                                    common_sqlite3.cleanup_sql_table(job_mem_db_file, job_mem_db_conn, job_table_name, commit=False)
                                    job_table_list.remove(job_table_name)

                    # Generate sql table if not exitst.
                    if job_table_name not in job_table_list:
                        common_sqlite3.create_sql_table(job_mem_db_file, job_mem_db_conn, job_table_name, key_string, commit=False)

                    # Insert sql table value.
                    value_list = [self.sample_second, self.sample_time, bjobs_dic[job]['mem']]
                    value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                    common_sqlite3.insert_into_sql_table(job_mem_db_file, job_mem_db_conn, job_table_name, value_string, commit=False)

                job_mem_db_conn.commit()
                job_mem_db_conn.close()

        common.bprint('Done (' + str(len(job_list)) + ' jobs).', date_format='%Y-%m-%d %H:%M:%S', indent=4)

    def sample_queue_info(self):
        """
        Sample queue info and save it into sqlite db.
        """
        common.bprint('>>> Sampling queue info ...', date_format='%Y-%m-%d %H:%M:%S')

        queue_db_file = str(self.db_path) + '/queue.db'
        (result, queue_db_conn) = common_sqlite3.connect_db_file(queue_db_file, mode='write')

        if result == 'passed':
            queue_table_list = common_sqlite3.get_sql_table_list(queue_db_file, queue_db_conn)
            bhosts_dic = common_lsf.get_bhosts_info()
            queue_host_dic = common_lsf.get_queue_host_info()
            bqueues_dic = common_lsf.get_bqueues_info()
            queue_list = bqueues_dic['QUEUE_NAME']
            queue_list.append('ALL')

            key_list = ['sample_second', 'sample_time', 'TOTAL', 'NJOBS', 'PEND', 'RUN', 'SUSP']
            key_type_list = ['INTEGER PRIMARY KEY', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT']
            key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

            for i in range(len(queue_list)):
                queue = queue_list[i]
                queue_table_name = 'queue_' + str(queue)

                # Generate sql table if not exitst.
                if queue_table_name not in queue_table_list:
                    common_sqlite3.create_sql_table(queue_db_file, queue_db_conn, queue_table_name, key_string, commit=False)

                # Insert sql table value.
                total_slots = 0

                if queue == 'ALL':
                    for max in bhosts_dic['MAX']:
                        if re.match(r'^\d+$', max):
                            total_slots += int(max)

                    value_list = [self.sample_second, self.sample_time, total_slots, sum([int(i) for i in bqueues_dic['NJOBS']]), sum([int(i) for i in bqueues_dic['PEND']]), sum([int(i) for i in bqueues_dic['RUN']]), sum([int(i) for i in bqueues_dic['SUSP']])]
                elif queue == 'lost_and_found':
                    value_list = [self.sample_second, self.sample_time, 'N/A', bqueues_dic['NJOBS'][i], bqueues_dic['PEND'][i], bqueues_dic['RUN'][i], bqueues_dic['SUSP'][i]]
                else:
                    for queue_host in queue_host_dic[queue]:
                        host_index = bhosts_dic['HOST_NAME'].index(queue_host)
                        host_max = bhosts_dic['MAX'][host_index]

                        if re.match(r'^\d+$', host_max):
                            total_slots += int(host_max)

                    value_list = [self.sample_second, self.sample_time, total_slots, bqueues_dic['NJOBS'][i], bqueues_dic['PEND'][i], bqueues_dic['RUN'][i], bqueues_dic['SUSP'][i]]

                value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                common_sqlite3.insert_into_sql_table(queue_db_file, queue_db_conn, queue_table_name, value_string, commit=False)

            queue_db_conn.commit()
            queue_db_conn.close()

    def sample_host_info(self):
        """
        Sample host info and save it into sqlite db.
        """
        common.bprint('>>> Sampling host info ...', date_format='%Y-%m-%d %H:%M:%S')

        host_db_file = str(self.db_path) + '/host.db'
        (result, host_db_conn) = common_sqlite3.connect_db_file(host_db_file, mode='write')

        if result == 'passed':
            host_table_list = common_sqlite3.get_sql_table_list(host_db_file, host_db_conn)
            bhosts_dic = common_lsf.get_bhosts_info()
            host_list = bhosts_dic['HOST_NAME']

            key_list = ['sample_second', 'sample_time', 'NJOBS', 'RUN', 'SSUSP', 'USUSP']
            key_type_list = ['INTEGER PRIMARY KEY', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT']
            key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

            for i in range(len(host_list)):
                host = host_list[i]
                host_table_name = 'host_' + str(host)

                # Generate sql table if not exists.
                if host_table_name not in host_table_list:
                    common_sqlite3.create_sql_table(host_db_file, host_db_conn, host_table_name, key_string, commit=False)

                # Insert sql table value.
                value_list = [self.sample_second, self.sample_time, bhosts_dic['NJOBS'][i], bhosts_dic['RUN'][i], bhosts_dic['SSUSP'][i], bhosts_dic['USUSP'][i]]
                value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                common_sqlite3.insert_into_sql_table(host_db_file, host_db_conn, host_table_name, value_string, commit=False)

            host_db_conn.commit()
            host_db_conn.close()

    def sample_load_info(self):
        """
        Sample host load info and save it into sqlite db.
        """
        common.bprint('>>> Sampling host load info ...', date_format='%Y-%m-%d %H:%M:%S')

        load_db_file = str(self.db_path) + '/load.db'
        (result, load_db_conn) = common_sqlite3.connect_db_file(load_db_file, mode='write')

        if result == 'passed':
            load_table_list = common_sqlite3.get_sql_table_list(load_db_file, load_db_conn)

            if self.tool == 'openlava':
                lsload_dic = common_lsf.get_lsload_info(command='lsload -l')
            else:
                lsload_dic = common_lsf.get_lsload_info()

            host_list = lsload_dic['HOST_NAME']

            key_list = ['sample_second', 'sample_time', 'ut', 'tmp', 'swp', 'mem']
            key_type_list = ['INTEGER PRIMARY KEY', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT']
            key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

            for i in range(len(host_list)):
                host = host_list[i]
                load_table_name = 'load_' + str(host)

                # Generate sql table if not exists.
                if load_table_name not in load_table_list:
                    common_sqlite3.create_sql_table(load_db_file, load_db_conn, load_table_name, key_string, commit=False)

                # Update "ut" value.
                if not lsload_dic['ut'][i]:
                    lsload_dic['ut'][i] = '0%'
                else:
                    ut = re.sub(r'%', '', lsload_dic['ut'][i])

                    if re.match(r'^\d+\.\d+$', ut):
                        ut = str(int(float(ut)))

                    if int(ut) > 100:
                        ut = '100'

                    lsload_dic['ut'][i] = str(ut) + '%'

                # Insert sql table value.
                value_list = [self.sample_second, self.sample_time, lsload_dic['ut'][i], lsload_dic['tmp'][i], lsload_dic['swp'][i], lsload_dic['mem'][i]]
                value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                common_sqlite3.insert_into_sql_table(load_db_file, load_db_conn, load_table_name, value_string, commit=False)

            load_db_conn.commit()
            load_db_conn.close()

    def sample_user_info(self):
        """
        Sample user info.
        """
        common.bprint('>>> Sampling job info ...', date_format='%Y-%m-%d %H:%M:%S')
        common.bprint('* Getting finished job information with command "bjobs -u all -d -UF" ...', date_format='%Y-%m-%d %H:%M:%S', indent=4)
        bjobs_dic = common_lsf.get_bjobs_uf_info('bjobs -u all -d -UF')

        # Re-organize jobs_dic with finished_date.
        date_bjobs_dic = {}

        for job in bjobs_dic.keys():
            finished_date = common_lsf.switch_bjobs_uf_time(bjobs_dic[job]['finished_time'], '%Y%m%d')
            date_bjobs_dic.setdefault(finished_date, {})
            user = bjobs_dic[job]['user']
            date_bjobs_dic[finished_date].setdefault(user, {})
            date_bjobs_dic[finished_date][user][job] = {'status': bjobs_dic[job]['status'], 'queue': bjobs_dic[job]['queue'], 'project': bjobs_dic[job]['project'], 'rusage_mem': bjobs_dic[job]['rusage_mem'], 'max_mem': bjobs_dic[job]['max_mem']}

        # Write db_file with finished_date.
        common.bprint('* Saving user job information ...', date_format='%Y-%m-%d %H:%M:%S', indent=4)
        key_list = ['job', 'status', 'queue', 'project', 'rusage_mem', 'max_mem']
        key_type_list = ['PRIMARY KEY', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT']
        key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

        for finished_date in date_bjobs_dic.keys():
            finished_date_db_file = str(self.user_db_path) + '/' + str(finished_date) + '.db'
            common.bprint('Writing ' + str(finished_date_db_file) + ' ...', date_format='%Y-%m-%d %H:%M:%S', indent=6)
            (result, finished_date_db_conn) = common_sqlite3.connect_db_file(finished_date_db_file, mode='write')

            if result == 'passed':
                user_table_list = common_sqlite3.get_sql_table_list(finished_date_db_file, finished_date_db_conn)

                for user in date_bjobs_dic[finished_date]:
                    user_table_name = 'user_' + str(user)

                    # Generate sql table (user) if not exitst.
                    if user_table_name not in user_table_list:
                        common_sqlite3.create_sql_table(finished_date_db_file, finished_date_db_conn, user_table_name, key_string, commit=False)

                    for job in date_bjobs_dic[finished_date][user]:
                        # Insert sql table value if not exists.
                        value_list = [job, bjobs_dic[job]['status'], bjobs_dic[job]['queue'], bjobs_dic[job]['project'], bjobs_dic[job]['rusage_mem'], bjobs_dic[job]['max_mem']]
                        value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                        common_sqlite3.insert_into_sql_table(finished_date_db_file, finished_date_db_conn, user_table_name, value_string, commit=False)

                finished_date_db_conn.commit()
                finished_date_db_conn.close()

        common.bprint('Done (' + str(len(bjobs_dic.keys())) + ' jobs).', date_format='%Y-%m-%d %H:%M:%S', indent=4)

    def sample_utilization_info(self):
        """
        Sample host resource utilization info and save it into sqlite db.
        """
        common.bprint('>>> Sampling utilization info ...', date_format='%Y-%m-%d %H:%M:%S')

        utilization_db_file = str(self.db_path) + '/utilization.db'
        (result, utilization_db_conn) = common_sqlite3.connect_db_file(utilization_db_file, mode='write')

        if result == 'passed':
            utilization_table_list = common_sqlite3.get_sql_table_list(utilization_db_file, utilization_db_conn)
            bhosts_dic = common_lsf.get_bhosts_info()
            lshosts_dic = common_lsf.get_lshosts_info()

            if self.tool == 'openlava':
                lsload_dic = common_lsf.get_lsload_info(command='lsload -l')
            else:
                lsload_dic = common_lsf.get_lsload_info()

            host_list = lsload_dic['HOST_NAME']

            key_list = ['sample_second', 'sample_time', 'slot', 'cpu', 'mem']
            key_type_list = ['INTEGER PRIMARY KEY', 'TEXT', 'TEXT', 'TEXT', 'TEXT']
            key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

            for i in range(len(host_list)):
                host = host_list[i]
                utilization_table_name = 'utilization_' + str(host)

                # Generate sql table if not exists.
                if utilization_table_name not in utilization_table_list:
                    common_sqlite3.create_sql_table(utilization_db_file, utilization_db_conn, utilization_table_name, key_string, commit=False)

                # Get slot_utilization.
                slot_utilization = 0

                for (j, host_name) in enumerate(bhosts_dic['HOST_NAME']):
                    if (host_name == host) and re.match(r'^\d+$', bhosts_dic['NJOBS'][j]) and re.match(r'^\d+$', bhosts_dic['MAX'][j]) and (int(bhosts_dic['MAX'][j]) != 0):
                        slot_utilization = round(int(bhosts_dic['NJOBS'][j])/int(bhosts_dic['MAX'][j])*100, 1)

                        if int(slot_utilization) > 100:
                            common.bprint('For host "' + str(host) + '", invalid slot utilization "' + str(slot_utilization) + '".', date_format='%Y-%m-%d %H:%M:%S', level='Warning', indent=4)

                            if bhosts_dic['STATUS'][j] == 'unavail':
                                slot_utilization = 0.0
                            else:
                                slot_utilization = 100.0

                        break

                # Get cpu_utilization.
                cpu_utilization = 0

                if re.match(r'^\d+%$', lsload_dic['ut'][i]):
                    cpu_utilization = re.sub('%', '', lsload_dic['ut'][i])

                # Get mem_utilization.
                mem_utilization = 0

                for (k, host_name) in enumerate(lshosts_dic['HOST_NAME']):
                    if (host_name == host) and re.match(r'^(\d+(\.\d+)?)([MGT])$', lshosts_dic['maxmem'][k]) and re.match(r'^(\d+(\.\d+)?)([MGT])$', lsload_dic['mem'][i]):
                        # Get maxmem with MB.
                        maxmem_match = re.match(r'^(\d+(\.\d+)?)([MGT])$', lshosts_dic['maxmem'][k])
                        maxmem = float(maxmem_match.group(1))
                        maxmem_unit = maxmem_match.group(3)

                        if maxmem_unit == 'G':
                            maxmem = maxmem*1024
                        elif maxmem_unit == 'T':
                            maxmem = maxmem*1024*1024

                        # Get mem with MB.
                        mem_match = re.match(r'^(\d+(\.\d+)?)([MGT])$', lsload_dic['mem'][i])
                        mem = float(mem_match.group(1))
                        mem_unit = mem_match.group(3)

                        if mem_unit == 'G':
                            mem = mem*1024
                        elif mem_unit == 'T':
                            mem = mem*1024*1024

                        mem_utilization = round((maxmem-mem)*100/maxmem, 1)

                        if int(mem_utilization) > 100:
                            common.bprint('For host "' + str(host) + '", invalid mem utilization "' + str(mem_utilization) + '".', date_format='%Y-%m-%d %H:%M:%S', level='Warning', indent=4)
                            mem_utilization = 100.0

                        break

                # Insert sql table value.
                value_list = [self.sample_second, self.sample_time, slot_utilization, cpu_utilization, mem_utilization]
                value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                common_sqlite3.insert_into_sql_table(utilization_db_file, utilization_db_conn, utilization_table_name, value_string, commit=False)

            utilization_db_conn.commit()
            utilization_db_conn.close()

    def get_utilization_day_info(self):
        """
        Get current day slot/cpu/mem utilizaiton info from sqlite3 database.
        Reture slot/cpu/mem average utilization info with utilization_day_dic.
        """
        utilization_day_dic = {}
        begin_time = str(self.sample_date) + ' 00:00:00'
        begin_second = time.mktime(time.strptime(begin_time, '%Y%m%d %H:%M:%S'))
        end_time = str(self.sample_date) + ' 23:59:59'
        end_second = time.mktime(time.strptime(end_time, '%Y%m%d %H:%M:%S'))
        select_condition = "WHERE sample_second BETWEEN '" + str(begin_second) + "' AND '" + str(end_second) + "'"

        utilization_db_file = str(self.db_path) + '/utilization.db'
        (result, utilization_db_conn) = common_sqlite3.connect_db_file(utilization_db_file, mode='write')

        if result == 'passed':
            utilization_table_list = common_sqlite3.get_sql_table_list(utilization_db_file, utilization_db_conn)

            for utilization_table_name in utilization_table_list:
                # Get current day issued/in_use/utilization from sqlite3 database.
                utilization_db_data_dic = common_sqlite3.get_sql_table_data(utilization_db_file, utilization_db_conn, utilization_table_name, ['slot', 'cpu', 'mem'], select_condition)

                if utilization_db_data_dic:
                    # Get slot_sum/cpu_sum/mem_sum info.
                    slot_utilization_sum = 0
                    cpu_utilization_sum = 0
                    mem_utilization_sum = 0

                    for (i, slot) in enumerate(utilization_db_data_dic['slot']):
                        slot_utilization_sum += float(utilization_db_data_dic['slot'][i])
                        cpu_utilization_sum += float(utilization_db_data_dic['cpu'][i])
                        mem_utilization_sum += float(utilization_db_data_dic['mem'][i])

                    # Get slot_avg/cpu_avg/mem_avg utilizaiton info.
                    slot_avg_utilization = round(slot_utilization_sum/len(utilization_db_data_dic['slot']), 1)
                    cpu_avg_utilization = round(cpu_utilization_sum/len(utilization_db_data_dic['slot']), 1)
                    mem_avg_utilization = round(mem_utilization_sum/len(utilization_db_data_dic['slot']), 1)

                    if int(slot_avg_utilization) > 100:
                        common.bprint('For db table "' + str(utilization_table_name) + '", invalid slot average utilization "' + str(slot_avg_utilization) + '".', date_format='%Y-%m-%d %H:%M:%S', level='Warning', indent=4)
                        slot_avg_utilization = 100.0

                    if int(cpu_avg_utilization) > 100:
                        common.bprint('For db table "' + str(utilization_table_name) + '", invalid cpu average utilization "' + str(cpu_avg_utilization) + '".', date_format='%Y-%m-%d %H:%M:%S', level='Warning', indent=4)
                        cpu_avg_utilization = 100.0

                    if int(mem_avg_utilization) > 100:
                        common.bprint('For db table "' + str(utilization_table_name) + '", invalid mem average utilization "' + str(mem_avg_utilization) + '".', date_format='%Y-%m-%d %H:%M:%S', level='Warning', indent=4)
                        mem_avg_utilization = 100.0

                    utilization_day_dic[utilization_table_name] = {'slot': slot_avg_utilization, 'cpu': cpu_avg_utilization, 'mem': mem_avg_utilization}

        return utilization_day_dic

    def count_utilization_day_info(self):
        """
        Count host resource utilization day average info and save it into sqlite db.
        """
        common.bprint('>>> Counting utilization (day average) info ...', date_format='%Y-%m-%d %H:%M:%S')

        utilization_day_db_file = str(self.db_path) + '/utilization_day.db'
        (result, utilization_day_db_conn) = common_sqlite3.connect_db_file(utilization_day_db_file, mode='write')

        if result == 'passed':
            utilization_day_table_list = common_sqlite3.get_sql_table_list(utilization_day_db_file, utilization_day_db_conn)
            utilization_day_dic = self.get_utilization_day_info()

            key_list = ['sample_date', 'slot', 'cpu', 'mem']
            key_type_list = ['TEXT PRIMARY KEY', 'TEXT', 'TEXT', 'TEXT']
            key_string = common_sqlite3.gen_sql_table_key_string(key_list, key_type_list)

            for (utilization_day_table_name, utilization_day_table_dic) in utilization_day_dic.items():
                host = re.sub('utilization_', '', utilization_day_table_name)
                common.bprint('Counting utilization (day average) info for host "' + str(host) + '" ...', date_format='%Y-%m-%d %H:%M:%S', indent=4)

                # Generate sql table.
                if utilization_day_table_name not in utilization_day_table_list:
                    common_sqlite3.create_sql_table(utilization_day_db_file, utilization_day_db_conn, utilization_day_table_name, key_string, commit=False)

                    # Insert sql table value.
                    value_list = [self.sample_date, utilization_day_table_dic['slot'], utilization_day_table_dic['cpu'], utilization_day_table_dic['mem']]
                    value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                    common_sqlite3.insert_into_sql_table(utilization_day_db_file, utilization_day_db_conn, utilization_day_table_name, value_string, commit=False)
                else:
                    select_condition = "WHERE sample_date='" + str(self.sample_date) + "'"
                    utilization_day_db_data_dic = common_sqlite3.get_sql_table_data(utilization_day_db_file, utilization_day_db_conn, utilization_day_table_name, ['slot', 'cpu', 'mem'], select_condition)

                    if utilization_day_db_data_dic:
                        # Replace sql table value.
                        set_condition = "SET slot='" + str(utilization_day_table_dic['slot']) + "', cpu='" + str(utilization_day_table_dic['cpu']) + "', mem='" + str(utilization_day_table_dic['mem']) + "'"
                        where_condition = "WHERE sample_date='" + str(self.sample_date) + "'"
                        common_sqlite3.update_sql_table_data(utilization_day_db_file, utilization_day_db_conn, utilization_day_table_name, set_condition, where_condition, commit=False)
                    else:
                        # Insert sql table value.
                        value_list = [self.sample_date, utilization_day_table_dic['slot'], utilization_day_table_dic['cpu'], utilization_day_table_dic['mem']]
                        value_string = common_sqlite3.gen_sql_table_value_string(value_list)
                        common_sqlite3.insert_into_sql_table(utilization_day_db_file, utilization_day_db_conn, utilization_day_table_name, value_string, commit=False)

            utilization_day_db_conn.commit()
            utilization_day_db_conn.close()

    def sampling(self):
        # Cleanup.
        if self.cleanup:
            self.cleanup_db()

        # Sample.
        sample_mark = False

        if self.job_sampling:
            sample_mark = True
            p = Process(target=self.sample_job_info)
            p.start()

        if self.job_mem_sampling:
            sample_mark = True
            p = Process(target=self.sample_job_mem_info)
            p.start()

        if self.queue_sampling:
            sample_mark = True
            p = Process(target=self.sample_queue_info)
            p.start()

        if self.host_sampling:
            sample_mark = True
            p = Process(target=self.sample_host_info)
            p.start()

        if self.load_sampling:
            sample_mark = True
            p = Process(target=self.sample_load_info)
            p.start()

        if self.user_sampling:
            sample_mark = True
            p = Process(target=self.sample_user_info)
            p.start()

        if self.utilization_sampling:
            sample_mark = True
            p = Process(target=self.sample_utilization_info)
            p.start()

        if self.utilization_day_sampling:
            sample_mark = True
            p = Process(target=self.count_utilization_day_info)
            p.start()

        if sample_mark:
            p.join()


#################
# Main Function #
#################
def main():
    (cleanup, job, job_mem, queue, host, load, user, utilization, utilization_day) = read_args()
    my_sampling = Sampling(cleanup, job, job_mem, queue, host, load, user, utilization, utilization_day)
    my_sampling.sampling()


if __name__ == '__main__':
    main()
