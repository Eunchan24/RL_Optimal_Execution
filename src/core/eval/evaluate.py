import numpy as np
import os
import random
from os.path import isdir, isfile, join
import re
from datetime import datetime
import matplotlib.pyplot as plt

import ray
from ray import tune
from ray.tune.registry import register_env
from ray.rllib.models import ModelCatalog

from tqdm import tqdm
from train_app import lob_env_creator, init_arg_parser, config, ROOT_DIR, DATA_DIR
from ray.rllib.agents.ppo import PPOTrainer

from src.core.agent.ray_model import CustomRNNModel


def eval_agent_one_day(trainer, env, nr_episodes,session_dir,day, plot=True, ):

    reward_vec = []
    vwap_bmk = []
    vwap_rl = []
    vol_percentages = []

    for _ in tqdm(range(nr_episodes), desc="Evaluation of agent"):
        obs = env.reset()
        episode_reward = 0
        done = False
        state = trainer.get_policy().get_initial_state()
        while not done:
            action, state, _ = trainer.compute_action(obs,state = state)
            obs, reward, done, info = env.step(action)
            episode_reward += reward

        reward_vec.append(episode_reward)
        vwap_bmk.append(env.broker.benchmark_algo.bmk_vwap)
        vwap_rl.append(env.broker.rl_algo.rl_vwap)
        vol_percentages.append(np.mean(np.array(env.broker.rl_algo.volumes_per_trade)/
                                     np.array(env.broker.rl_algo.bucket_volumes)[:,None],axis= 0,dtype=np.float32))

    outperf = [True if vwap > vwap_rl[idx] else False for idx, vwap in enumerate(vwap_bmk)]
    vwap_perc_diff = (np.array(vwap_bmk)-np.array(vwap_rl)) / np.array(vwap_bmk)
    downside_median = np.median(vwap_perc_diff[outperf])
    upside_median = np.median(vwap_perc_diff[[not elem for elem in outperf]])
    vol_percentages_avg, error_vol_percentages = tolerant_mean(vol_percentages)

    # after each episode, collect execution prices
    d_out = {'rewards': np.array(reward_vec),
             'vwap_bmk': np.array(vwap_bmk),
             'vwap_rl': np.array(vwap_rl),
             'vwap_diff': vwap_perc_diff,
             'vol_percentages': np.array(vol_percentages_avg),
             'vol_percentages_error': np.array(error_vol_percentages)}
    stats = {'percentage_outperformance': sum(outperf)/len(outperf),
             'downside_median': downside_median,
             'upside_median': upside_median}

    if plot:
        plot_eval_day(session_dir, d_out, day)

    return d_out, stats

def eval_agent(trainer, env, nr_episodes,session_dir, plot=True, ):

    reward_vec = []
    vwap_bmk = []
    vwap_rl = []
    vol_percentages = []

    for _ in tqdm(range(nr_episodes), desc="Evaluation of agent"):
        obs = env.reset()
        episode_reward = 0
        done = False
        state = trainer.get_policy().get_initial_state()
        while not done:
            action, state, _ = trainer.compute_action(obs,state = state)
            obs, reward, done, info = env.step(action)
            episode_reward += reward

        reward_vec.append(episode_reward)
        vwap_bmk.append(env.broker.benchmark_algo.bmk_vwap)
        vwap_rl.append(env.broker.rl_algo.rl_vwap)
        vol_percentages.append(np.mean(np.array(env.broker.rl_algo.volumes_per_trade)/
                                       np.array(env.broker.rl_algo.bucket_volumes)[:,None],axis= 0,dtype=np.float32))

    outperf = [True if vwap > vwap_rl[idx] else False for idx, vwap in enumerate(vwap_bmk)]
    vwap_perc_diff = (np.array(vwap_bmk)-np.array(vwap_rl)) / np.array(vwap_bmk)
    downside_median = np.median(vwap_perc_diff[outperf])
    upside_median = np.median(vwap_perc_diff[[not elem for elem in outperf]])
    vol_percentages_avg, error_vol_percentages = tolerant_mean(vol_percentages)

    # after each episode, collect execution prices
    d_out = {'rewards': np.array(reward_vec),
             'vwap_bmk': np.array(vwap_bmk),
             'vwap_rl': np.array(vwap_rl),
             'vwap_diff': vwap_perc_diff,
             'vol_percentages': np.array(vol_percentages_avg),
             'vol_percentages_error': np.array(error_vol_percentages)}
    stats = {'percentage_outperformance': sum(outperf)/len(outperf),
             'downside_median': downside_median,
             'upside_median': upside_median}

    if plot:
        plot_eval_days(session_dir, d_out, days_class= 'all')

    return d_out, stats


def plot_eval_day(session_dir, d_out, day):
    fig, axs = plt.subplots(2, 2, figsize=(14,10))

    plt.suptitle("Evaluation on {}, daily volatility: {} ".format(day,
                                                                  env.broker.data_feed.day_volatilities[env.broker.data_feed.day_volatilities_ranking[env.broker.data_feed.binary_file_idx]] ), fontsize=14)


    axs[0, 0].hist(d_out['rewards'], density=True, bins=50)
    axs[0, 0].set_title('Rewards from RL Agent')
    axs[0, 0].set(xlabel='Reward', ylabel='Frequency')

    axs[0, 1].hist(d_out['vwap_bmk'], alpha=0.5, density=True, bins=50, label= 'Benchmark VWAP')
    axs[0, 1].hist(d_out['vwap_rl'], alpha=0.5, density=True, bins=50, label = 'RL VWAP')
    axs[0, 1].set_title('Benchmark and RL Execution Price')
    axs[0, 1].set(xlabel='Execution Price', ylabel='Probability')
    axs[0, 1].legend(loc = "upper left")

    axs[1, 0].hist(100*d_out['vwap_diff'], density=True, bins=50)
    axs[1, 0].set_title('Difference of Benchmark vs. RL Execution Price')
    axs[1, 0].set(xlabel='Execution Price Difference (%)', ylabel='Probability')

    axs[1, 1].bar(np.arange(len(d_out['vol_percentages'])),100*d_out['vol_percentages'],
                  align='center',
                  alpha=0.5,
                  ecolor='black',
                  capsize=10)
    axs[1, 1].set_title('Average % of the volume executed per Order Placement in Bucket')
    axs[1, 1].set(xlabel= 'Order Number', ylabel= 'Volume (%)')

    # plt.show()

    fig.savefig(session_dir + r"\evaluation_graphs_{}.png".format(day))

def plot_eval_days(session_dir, d_outs_list, days_class):
    d_out = {}
    for k in d_outs_list[0].keys():
        if k!='vol_percentages':
            d_out[k] = np.concatenate(list(d[k] for d in d_outs_list))
        else:
            d_out[k], _ = tolerant_mean(list(d[k] for d in d_outs_list))

    fig, axs = plt.subplots(2, 2, figsize=(14,10))
    plt.suptitle("Evaluation on {} days ".format(days_class), fontsize=14)

    axs[0, 0].hist(d_out['rewards'], density=True, bins=50)
    axs[0, 0].set_title('Rewards from RL Agent')
    axs[0, 0].set(xlabel='Reward', ylabel='Frequency')

    axs[0, 1].hist(d_out['vwap_bmk'], alpha=0.5, density=True, bins=50, label= 'Benchmark VWAP')
    axs[0, 1].hist(d_out['vwap_rl'], alpha=0.5, density=True, bins=50, label = 'RL VWAP')
    axs[0, 1].set_title('Benchmark and RL Execution Price')
    axs[0, 1].set(xlabel='Execution Price', ylabel='Probability')
    axs[0, 1].legend(loc = "upper left")

    axs[1, 0].hist(100*d_out['vwap_diff'], density=True, bins=50)
    axs[1, 0].set_title('Difference of Benchmark vs. RL Execution Price')
    axs[1, 0].set(xlabel='Execution Price Difference (%)', ylabel='Probability')

    axs[1, 1].bar(np.arange(len(d_out['vol_percentages'])),100*d_out['vol_percentages'],
                  align='center',
                  alpha=0.5,
                  ecolor='black',
                  capsize=10)
    axs[1, 1].set_title('Average % of the volume executed per Order Placement in Bucket')
    axs[1, 1].set(xlabel= 'Order Number', ylabel= 'Volume (%)')

    # plt.show()

    fig.savefig(session_dir + r"\evaluation_graphs_{}_days.png".format(days_class))


def get_session_best_checkpoint_path(session_path, session,):

    session_path = session_path + r'\{}\PPO'.format(str(session))
    session_filename = [f for f in os.listdir(session_path) if isdir(join(session_path, f))]
    sessions_path = session_path + r'\{}'.format(session_filename[0])

    analysis = tune.Analysis(sessions_path)  # can also be the result of `tune.run()`

    trial_logdir = analysis.get_best_logdir(metric="episode_reward_mean", mode="max")  # Can also just specify trial dir directly

    # checkpoints = analysis.get_trial_checkpoints_paths(trial_logdir)  # Returns tuples of (logdir, metric)
    best_checkpoint = analysis.get_best_checkpoint(trial_logdir, metric="episode_reward_mean", mode="max")

    return best_checkpoint

def tolerant_mean(arrs):
    lens = [len(i) for i in arrs]
    arr = np.ma.empty((np.max(lens),len(arrs)))
    arr.mask = True
    for idx, l in enumerate(arrs):
        arr[:len(l),idx] = l
    return arr.mean(axis = -1), arr.std(axis=-1)


def get_n_highest_and_lowest_vol_days(env,n):

    env.broker.data_feed.get_daily_vols()
    # Get the dates of the desired days
    highest_vol_days = []
    lowest_vol_days = []
    for i in range(n):
        highest_vol_days.append(env.broker.data_feed.binary_files[
            env.broker.data_feed.day_volatilities_ranking[i]])
        lowest_vol_days.append(env.broker.data_feed.binary_files[
            env.broker.data_feed.day_volatilities_ranking[-(i+1)]])

    return highest_vol_days, lowest_vol_days


if __name__ == "__main__":

    args = init_arg_parser()

    # For debugging the ENV or other modules, set local_mode=True
    ray.init(num_cpus=args.num_cpus,
             local_mode=True,
             )

    sessions_path = ROOT_DIR + r'\data\sessions'
    sessions = [int(session_id) for session_id in os.listdir(sessions_path) if session_id !='.gitignore']
    checkpoint = get_session_best_checkpoint_path(session_path=sessions_path, session= np.max(sessions))

    config["env_config"]["train_config"]["train"] = False # To load only eval_data_periods data
    config["env_config"]["reset_config"]["reset_feed"] = False # To make sure we don't jump to the next day when evaluating on a given day
    config["num_workers"] = 0
    register_env("lob_env", lob_env_creator)
    ModelCatalog.register_custom_model("end_to_end_model", CustomRNNModel)


    agent = PPOTrainer(config=config)
    agent.restore(checkpoint)

    env = lob_env_creator(env_config= config["env_config"])

    highest_vol_days, lowest_vol_days = get_n_highest_and_lowest_vol_days(env,3)
    d_outs_list_high_vol = []
    d_outa_list_low_vol = []
    
    for day in range(len(highest_vol_days)):
        day_idx = env.broker.data_feed.day_volatilities_ranking[day]
        day_file = env.broker.data_feed.binary_files[day_idx]
        match = re.search(r'\d{4}_\d{2}_\d{2}', day_file)
        date = datetime.strptime(match.group(), '%Y_%m_%d').date()

        env.broker.data_feed.load_specific_day_data(day_idx)
        d_out, stats = eval_agent_one_day(trainer= agent,env= env ,nr_episodes= 25,session_dir = sessions_path + r'\{}\PPO'.format(str(np.max(sessions))),day = date, plot=False)
        d_outs_list_high_vol.append(d_out)

    plot_eval_days(session_dir=sessions_path + r'\{}\PPO'.format(str(np.max(sessions))), d_outs_list= d_outs_list_high_vol, days_class= 'High_Vol')

    for day in range(len(lowest_vol_days)):
        day_idx = env.broker.data_feed.day_volatilities_ranking[-(day+1)]
        day_file = env.broker.data_feed.binary_files[day_idx]
        match = re.search(r'\d{4}_\d{2}_\d{2}', day_file)
        date = datetime.strptime(match.group(), '%Y_%m_%d').date()

        env.broker.data_feed.load_specific_day_data(day_idx)
        d_out, stats = eval_agent_one_day(trainer= agent,env= env ,nr_episodes= 25,session_dir = sessions_path + r'\{}\PPO'.format(str(np.max(sessions))),day = date, plot=False)
        d_outa_list_low_vol.append(d_out)

    plot_eval_days(session_dir=sessions_path + r'\{}\PPO'.format(str(np.max(sessions))), d_outs_list= d_outa_list_low_vol, days_class= 'Low_Vol')

    # eval_agent(trainer= agent,env= env ,nr_episodes= 100,session_dir = sessions_path + r'\{}\PPO'.format(str(np.max(sessions))), plot=False)
