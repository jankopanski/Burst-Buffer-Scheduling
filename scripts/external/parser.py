#!/usr/bin/python

import argparse
import sys
import os
import random
from math import ceil, floor


# argc = len(sys.argv)
# job_from = int(sys.argv[2])
# job_to = int(sys.argv[3])

'''
0. Job Number -- a counter field, starting from 1.
1. Submit Time -- in seconds. The earliest time the log refers to is zero, and is usually the submittal time of the first job. The lines in the log are sorted by ascending submittal times. It makes sense for jobs to also be numbered in this order.
2. Wait Time -- in seconds. The difference between the job's submit time and the time at which it actually began to run. Naturally, this is only relevant to real logs, not to models.
3. Run Time -- in seconds. The wall clock time the job was running (end time minus start time).
We decided to use ``wait time'' and ``run time'' instead of the equivalent ``start time'' and ``end time'' because they are directly attributable to the scheduler and application, and are more suitable for models where only the run time is relevant.
Note that when values are rounded to an integral number of seconds (as often happens in logs) a run time of 0 is possible and means the job ran for less than 0.5 seconds. On the other hand it is permissable to use floating point values for time fields.
4. Number of Allocated Processors -- an integer. In most cases this is also the number of processors the job uses; if the job does not use all of them, we typically don't know about it.
5. Average CPU Time Used -- both user and system, in seconds. This is the average over all processors of the CPU time used, and may therefore be smaller than the wall clock runtime. If a log contains the total CPU time used by all the processors, it is divided by the number of allocated processors to derive the average.
6. Used Memory -- in kilobytes. This is again the average per processor.
7. Requested Number of Processors.
8. Requested Time. This can be either runtime (measured in wallclock seconds), or average CPU time per processor (also in seconds) -- the exact meaning is determined by a header comment. In many logs this field is used for the user runtime estimate (or upper bound) used in backfilling. If a log contains a request for total CPU time, it is divided by the number of requested processors.
9. Requested Memory (again kilobytes per processor).
10. Status 1 if the job was completed, 0 if it failed, and 5 if cancelled. If information about chekcpointing or swapping is included, other values are also possible. See usage note below. This field is meaningless for models, so would be -1.
11. User ID -- a natural number, between one and the number of different users.
12. Group ID -- a natural number, between one and the number of different groups. Some systems control resource usage by groups rather than by individual users.
13. Executable (Application) Number -- a natural number, between one and the number of different applications appearing in the workload. in some logs, this might represent a script file used to run jobs rather than the executable directly; this should be noted in a header comment.
14. Queue Number -- a natural number, between one and the number of different queues in the system. The nature of the system's queues should be explained in a header comment. This field is where batch and interactive jobs should be differentiated: we suggest the convention of denoting interactive jobs by 0.
15. Partition Number -- a natural number, between one and the number of different partitions in the systems. The nature of the system's partitions should be explained in a header comment. For example, it is possible to use partition numbers to identify which machine in a cluster was used.
16. Preceding Job Number -- this is the number of a previous job in the workload, such that the current job can only start after the termination of this preceding job. Together with the next field, this allows the workload to include feedback as described below.
17. Think Time from Preceding Job -- this is the number of seconds that should elapse between the termination of the preceding job and the submittal of this one.
'''
COLS = [
        'job_number',
        'submit_time',
        'wait_time',
        'run_time',
        'allocated_processors',
        'average_cpu_time_used',
        'used_memory',
        'requested_processors',
        'requested_time',
        'requested_memory',
        'status',
        'user_id',
        'group_id',
        'application_number',
        'queue_number',
        'partition_number',
        'preceding_job_number',
        'think_time']

COL_NUM = dict(zip(COLS, range(len(COLS))))

class JobRecord(object):
    def csv_line(self, header):
        header = header.split(',')
        m = {}
        for i, col in enumerate(header):
            m[col] = i

        col_to_val = {}

        def add_col(col, val):
            col_to_val[m[col]] = val

        add_col('job', self.job_number)
        add_col('submit', self.submit_time)
        add_col('run', self.run_time)
        add_col('nodes', self.nodes_cnt)
        add_col('bb', self.bb)

        line = []

        for i in range(len(header)):
            line.append(col_to_val.get(i, -1))

        return ','.join(map(str, line))


    @staticmethod
    def from_csv_line(header, line):
        header = header.split(',')
        m = {}
        for i, col in enumerate(header):
            m[col] = i

        line = [int(el) for el in line.split(',')]
        record = JobRecord()

        def read_col(col):
            return line[m[col]] if col in m else None

        record.job_number = read_col('job')
        record.submit_time = read_col('submit')
        record.run_time = read_col('run')
        record.nodes_cnt = read_col('nodes')
        record.bb = read_col('bb')

        return record

    @staticmethod
    def from_swf_line(line):
        record = JobRecord()
        cols = [int(x) for x in line.split()]
        record.cols = dict([(name, cols[num]) for name, num in COL_NUM.items()])
        record.job_number = record.cols['job_number']
        record.submit_time = record.cols['submit_time']
        record.run_time = record.cols['run_time']
        record.nodes_cnt = record.cols['allocated_processors']
        record.bb = None

        return record


class JobSet(object):
    def __init__(self, jobs):
        self.jobs = jobs

    @staticmethod
    def from_swf_file(input_file, job_from, job_to):
        with open(input_file, 'r') as f:
            jobs = []
            job_num = 0
            for line in f:
                if job_to and job_num > job_to:
                    break
                line = line.strip()

                if line.startswith(';'):
                    continue
                if job_num >= job_from:
                    jobs.append(JobRecord.from_swf_line(line))
                    jobs[-1].job_number = job_num + 1 - job_from
                job_num += 1

        return JobSet(jobs)

    @staticmethod
    def from_csv_file(input_file):
        with open(input_file, 'r') as f:
            header = f.readline().strip()

            jobs = []
            for line in f:
                line = line.strip()
                jobs.append(JobRecord.from_csv_line(header, line))

        return JobSet(jobs)

    def normalize(self, scale, runscale):
        base_time = jobs[0].submit_time
        for job in self.jobs:
            job.submit_time = job.submit_time - base_time

        for job in self.jobs:
            job.submit_time = int(ceil(job.submit_time * scale))
            job.run_time = int(ceil(job.run_time * scale * runscale))

    def renumber(self):
        for i, job in enumerate(self.jobs):
            job.job_number = i + 1

    def scale_nodes_to_fit(self, nodes_limit, p=100.0):

        max_nodes = min([j[0] for j in self.nodes_intensity() if j[1] >= p])
        print 'max_nodes', max_nodes

        for job in self.jobs:
            job.nodes_cnt = int(floor(1.0 * nodes_limit * job.nodes_cnt / max_nodes))
            job.nodes_cnt = max(job.nodes_cnt, 1)
            job.nodes_cnt = min(job.nodes_cnt, nodes_limit)

    def scale_bb_to_fit(self, bb_limit, p=100.0):

        bb = min([j[0] for j in self.bb_intensity() if j[1] >=  p])
        print 'bb', bb

        for job in self.jobs:
            old = job.bb
            job.bb = int(ceil(1.0 * bb_limit * job.bb / bb))
            job.bb = min(job.bb, bb_limit)

    def bb_intensity(self):

        for j in self.jobs:
            j.run_time += 0

        result = list(self.intensity(lambda j: j.bb))

        for j in self.jobs:
            j.run_time -= 0

        return result

    def nodes_intensity(self):
        result = list(self.intensity(lambda j: j.nodes_cnt))

        return result

    def intensity(self, resource_fun):
        time_limit = max([j.submit_time + j.run_time for j in self.jobs])

        events = [0] * (time_limit + 1)
        
        for j in self.jobs:
            events[j.submit_time] += resource_fun(j)
            events[j.submit_time + j.run_time] -= resource_fun(j)

        resource_usage = [0] * (time_limit + 1)
        for i in range(time_limit):
            resource_usage[i] = events[i] + (resource_usage[i - 1] if i > 0 else 0)

        max_resource = max(resource_usage)

        print 'Max resource usage:', max_resource


        resource_ammounts = set()
        resource_time = [0] * (max_resource + 1)
        for i in range(0, time_limit):
            resource_time[resource_usage[i]] += 1
            resource_ammounts.add(resource_usage[i])

        resource_time_acc = [(-1, -1)] * len(resource_ammounts)
        for i, x in enumerate(sorted(resource_ammounts)):
            resource_time_acc[i] = [x, resource_time[x]]
            resource_time_acc[i][1] += resource_time_acc[i-1][1] if i > 0 else 0
            yield([ resource_time_acc[i][0], 100.0 * resource_time_acc[i][1]  / time_limit])

    def calc_max_node_usage(self):
        time_limit = max([j.submit_time + j.run_time for j in self.jobs])

        events = [0] * (time_limit + 1)

        for j in self.jobs:
            events[j.submit_time] += j.nodes_cnt
            events[j.submit_time + j.run_time] -= j.nodes_cnt

        resource_usage = [0] * (time_limit + 1)
        for i in range(time_limit):
            resource_usage[i] = events[i] + (resource_usage[i - 1] if i > 0 else 0)

        max_resource = max(resource_usage)

        return max_resource


    def filter_submit_time(self, time_from, time_to):
        self.jobs = filter(lambda job: time_from <= job.submit_time <= time_to, self.jobs)

    def filter_bad_jobs(self):
        self.jobs = filter(lambda job: job.nodes_cnt > 0, self.jobs)

    def assign_bb_intel(self):
        probs = [0.00166876893389,
                 0.42063449755599996,
                 0.262351216923,
                 0.136868816872,
                 0.13649928294,
                 0.00920598552054,
                 0.0102413577053,
                 0.00048670130610900005,
                 0.022043372243160917]

        bb = range(len(probs))

        self.assign_bb(zip(bb, probs))

    def assign_bb_meta(self):
        probs = [0.241659495881,
                 0.07570678541550001,
                 0.13974629652200002,
                 0.011540725625399999,
                 0.398633127286,
                 0.0219410437419,
                 0.036555855448,
                 0.00371123757816,
                 0.0536706005736,
                 0.005565938016860001,
                 0.0064773089395000006,
                 0.000820270564391,
                 0.00242187363682,
                 0.000162364348169,
                 0.000573234310672,
                 0.0008138421120277428]

        bb = range(len(probs))

        self.assign_bb(zip(bb, probs))

    def assign_bb(self, probs):

        for j in self.jobs:
            r = random.random()
            s = 0

            for bb, p in probs:
                if s <= r and r < s + p:
                    j.bb = bb
                    break

                s += p
        

    def print_stats(self):
        def _sec_to_time(s):
            res = '%02dd %02dh %02dm %02ds' % (s / (60*60*24), s / (60 * 60) % 24,s / 60 % 60,s%60)
            return res
        print '-' * 10
        print 'Number of jobs:', len(self.jobs)

        t = self.jobs[-1].submit_time - self.jobs[0].submit_time
        print 'Submit time span:', _sec_to_time(t)
        print 'Maximum run time:', _sec_to_time(max([j.run_time for j in self.jobs]))
        print 'Maximum run+submit time:', _sec_to_time(max([j.run_time + j.submit_time for j in self.jobs]))
        print '-' * 10

    def generate_csv(self):
        header = "job,submit,run,nodes,bb"
        csv = []
        csv.append(header)
        for j in self.jobs:
            csv.append(j.csv_line(header))

        return '\n'.join(csv)
        
def create_script(jobset, script_name=None):
    if not script_name:
        script_name = ''.join(map(lambda _: chr(random.randint(ord('A'), ord('Z'))), range(0, 6)))
    header = "#!/bin/bash\n"
    header += "# name = " + script_name + "\n"
    header += \
"""sudo kill -9 `pidof slurmctld`
sudo kill -9 `pidof slurmd`
sudo kill -9 `pidof munged`
sudo killall sleep
sudo rm -rf /var/log/slurm/*
sudo rm -rf /var/spool/slurm/*
sleep 1
sudo /usr/sbin/munged -f > /dev/null 2> /dev/null
sleep 1
. init_controller.sh
. init_workers.sh

"""
    print header
    dir = "SCRIPT_" + script_name
    script_file = "script_" + script_name + ".sh"
    csv_file = "script_" + script_name + ".csv"
    if not os.path.exists(dir):
        os.makedirs(dir)

    script = []
    trt = 0
    last_submit_time = 0

    for j in jobset.jobs:
        st = j.submit_time
        rt = j.run_time
        trt += rt

        t = j.run_time

        job_file = dir + ('/job%u.sh' % (j.job_number,))

        with open(job_file, 'w') as f:
            f.write('#!/bin/sh\n')
            if j.bb > 0:
                f.write('#DW jobdw type=scratch capacity=%uGB access_mode=striped\n' % (j.bb, ))
            f.write('sleep %u\n' % (t, ))
            

        script.append('sleep %u' % (j.submit_time - last_submit_time,))
        script.append('sbatch -N %d %s\n' % (j.nodes_cnt, job_file))
        last_submit_time = j.submit_time

    script = header + '\n'.join(script)


    with open(script_file, 'w') as f:
        f.write(script)
    with open(csv_file, 'w') as f:
        f.write(jobset.generate_csv())

    print 'Created ', script_name


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='SWF file parser')
    parser.add_argument(
        '--from', '-f', dest='job_from', default=0, type=int,
        help='the first job we want to consider')
    parser.add_argument(
        '--to', '-t', dest='job_to', default=None, type=int,
        help='the last job we want to consider')
    parser.add_argument(
        '--scale', '-s', dest='time_scale', default=1.0, type=float,
        help='scale whole time by a number')
    parser.add_argument(
        '--rscale', '-r', dest='run_time_scale', default=1.0, type=float,
        help='scale run time by a number')
    parser.add_argument(
        '--nobb', dest='no_bb', action='store_const', const=True, default=False,
        help='disable usage of burst buffers')
    parser.add_argument(
        '--name', '-n', dest='name', default='jazda10', type=str,
        help='name of the experiment')
    parser.add_argument(
        '--bb', dest='bb', default=70.0, type=float,
        help='bb')
    parser.add_argument(
        '--nodes', dest='nodes', default=100.0, type=float,
        help='nodes')
    parser.add_argument(
        '--bbdist', dest='bbdist', default=None, type=str,
        help='Meta/intel/none')
    parser.add_argument(
        'input_file',
        help='input swf file')
    args = parser.parse_args()
    print args

    random_state = random.getstate()

    random.seed(4321)

            
    jobset = JobSet.from_swf_file(args.input_file, args.job_from, args.job_to)
    jobs = jobset.jobs


    jobset.filter_bad_jobs()
    t = jobs[-1].submit_time - jobs[0].submit_time
    print t, t/60, t/60/60, t/60/60/24

    jobset.normalize(args.time_scale, args.run_time_scale)
    #print list(jobset.nodes_intensity())
    jobset.scale_nodes_to_fit(500, args.nodes)

    #print list(jobset.nodes_intensity())

    dist = '' if not args.bbdist else args.bbdist.lower()
    if dist == 'meta':
        jobset.assign_bb_meta()
    elif dist == 'intel':
        jobset.assign_bb_intel()
    else:
        jobset.assign_bb([(20, 0.2), (5, 0.4), (1, 0.4)])

    #print list(jobset.bb_intensity())
    jobset.scale_bb_to_fit(1024, args.bb)
    #print list(jobset.bb_intensity())

    print 'MAX USAGE', jobset.calc_max_node_usage()

    jobset.renumber()

    csv = jobset.generate_csv()
    with open('dupa', 'w') as f:
        f.write(csv)
    jobset2 = JobSet.from_csv_file('dupa')
    #print 'ARGH', str(csv == jobset2.generate_csv())

    random.setstate(random_state)


    def pretty_print(l):
        s = ''
        for el in l:
            s += str(el)
            s += ' '*(10 - len(str(el)))

        print s

    create_script(jobset, args.name)

