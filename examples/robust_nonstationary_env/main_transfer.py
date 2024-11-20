import os
import torch
import gym
import numpy as np
from utils.config import ARGConfig
from utils.default_config import default_config
from model.algo import OMPO
from model.discriminator import Discriminator_SAS
from utils.Replaybuffer import ReplayMemory
import datetime
import itertools
from copy import copy
from torch.utils.tensorboard import SummaryWriter
import shutil
import Non_stationary_env

def train_loop(config, msg = "default"):
    # set seed
    sim_env = gym.make(config.env_name)
    sim_env.seed(config.seed)
    sim_env.action_space.seed(config.seed)
    
    if "Hopper" in config.env_name:
        real_env = gym.make(config.env_name, torso_len = 0.4, foot_len = 0.39)
        real_env.seed(config.seed)
        real_env.action_space.seed(config.seed)
    elif "Walker" in config.env_name:
        real_env = gym.make(config.env_name, torso_len = 0.4, foot_len = 0.2)
        real_env.seed(config.seed)
        real_env.action_space.seed(config.seed)
    elif "Ant" in config.env_name:
        real_env = gym.make(config.env_name, gravity = 19.62, wind = 1)
        real_env.seed(config.seed)
        real_env.action_space.seed(config.seed)
    elif "Humanoid" in config.env_name:
        real_env = gym.make(config.env_name, gravity = 19.62, wind = 1)
        real_env.seed(config.seed)
        real_env.action_space.seed(config.seed)

    torch.manual_seed(config.seed)
    np.random.seed(config.seed)

    discriminator = Discriminator_SAS(sim_env.observation_space.shape[0], sim_env.action_space.shape[0], config)

    agent = OMPO(sim_env.observation_space.shape[0], sim_env.action_space, config)

    result_path = './results/{}/{}/{}/{}_{}_{}_{}'.format(config.env_name, config.algo, msg, 
                                                      datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"), 
                                                      'OMPO', config.seed, 
                                                      "autotune" if config.automatic_entropy_tuning else "")

    checkpoint_path = result_path + '/' + 'checkpoint'
    
    # training logs
    if not os.path.exists(result_path):
        os.makedirs(result_path)
    if not os.path.exists(checkpoint_path):
        os.makedirs(checkpoint_path)
    with open(os.path.join(result_path, "config.log"), 'w') as f:
        f.write(str(config))

    writer = SummaryWriter(result_path)
    shutil.copytree('.', result_path + '/code', ignore=shutil.ignore_patterns('results', 'results_stationary_test_1', 'results_stationary_test_2'))

    # all memory
    memory = ReplayMemory(config.replay_size, config.seed)
    initial_state_memory = ReplayMemory(config.replay_size, config.seed)
    # expert memory
    local_memory = ReplayMemory(config.local_replay_size, config.seed)
    # sample from all memory for training
    temp_memory = ReplayMemory(config.local_replay_size, config.seed)

    for _ in range(config.batch_size):
        state = real_env.reset()
        initial_state_memory.push(state, 0, 0, 0, 0) # Note the initial buffer only contains state

    # Training Loop
    total_numsteps = 0
    updates_discriminator = 0
    updates_agent = 0
    best_reward = -1e6
    for i_episode in itertools.count(1):
        episode_reward = 0
        episode_steps = 0
        done = False
        state = real_env.reset()
        initial_state_memory.push(state, 0, 0, 0, 0) # Note the initial buffer only contains state
        # sample in the real_env
        while not done:
            if config.start_steps > total_numsteps:
                action = real_env.action_space.sample()  # Sample random action
            else:
                action = agent.select_action(state)  # Sample action from policy

            if config.start_steps <= total_numsteps:
                # use the same history buffer to update the discriminator
                if local_memory.__len__() == config.local_replay_size:
                    for _ in range(10):  # default: 10
                        state_batch, action_batch, reward_batch, next_state_batch, mask_batch = memory.sample(batch_size=config.local_replay_size)
                        for local_buffer_idx in range(config.local_replay_size):
                            temp_memory.push(state_batch[local_buffer_idx], action_batch[local_buffer_idx], reward_batch[local_buffer_idx], next_state_batch[local_buffer_idx], mask_batch[local_buffer_idx])
                        for _ in range(20): # default: 20
                            discriminator_loss = discriminator.update(local_memory, temp_memory, config.gail_batch)
                            writer.add_scalar('loss/discriminator_loss', discriminator_loss, updates_discriminator)
                            updates_discriminator += 1
                            
                        temp_memory = ReplayMemory(config.local_replay_size, config.seed)
                    # reset the local memory
                    local_memory = ReplayMemory(config.local_replay_size, config.seed)
                
                # train the agent
                for _ in range(config.updates_per_step*10):
                    # Update parameters of all the networks
                    critic_loss, policy_loss, ent_loss, alpha = agent.update_parameters(initial_state_memory, memory, discriminator, config.batch_size, updates_agent)

                    writer.add_scalar('loss/critic', critic_loss, updates_agent)
                    writer.add_scalar('loss/policy', policy_loss, updates_agent)
                    writer.add_scalar('loss/entropy_loss', ent_loss, updates_agent)
                    writer.add_scalar('entropy_temprature/alpha', alpha, updates_agent)
                    updates_agent += 1

            next_state, reward, done, _ = real_env.step(action) # Step
            episode_steps += 1
            total_numsteps += 1
            episode_reward += reward

            # Ignore the "done" signal if it comes from hitting the time horizon.
            # (https://github.com/openai/spinningup/blob/master/spinup/algos/sac/sac.py)
            mask = 1 if episode_steps == real_env._max_episode_steps else float(not done)

            memory.push(state, action, reward + config.reward_max, next_state, mask) # Append transition to global memory
            local_memory.push(state, action, reward + config.reward_max, next_state, mask) # Append transition to local memory

            state = next_state

        
        # sample in the sim_env
        for _ in range(10):
            state = sim_env.reset()
            done = False
            while not done:
                if config.start_steps > total_numsteps:
                    action = sim_env.action_space.sample()  # Sample random action
                else:
                    action = agent.select_action(state)
                next_state, reward, done, _ = sim_env.step(action)
                mask = 1 if episode_steps == real_env._max_episode_steps else float(not done)
                memory.push(state, action, reward + config.reward_max, next_state, mask)
                state = next_state
                
        
        if total_numsteps > config.num_steps:
            break

        writer.add_scalar('train/reward', episode_reward, total_numsteps)
        print("Episode: {}, total numsteps: {}, episode steps: {}, reward: {}".format(i_episode, total_numsteps, episode_steps, round(episode_reward, 2)))

        # test agent
        if i_episode % config.eval_episodes == 0 and config.eval is True:
            avg_reward = 0.
            # avg_success = 0.
            for _  in range(config.eval_episodes):
                state = real_env.reset()
                episode_reward = 0
                done = False
                while not done:
                    action = agent.select_action(state, evaluate=True)

                    next_state, reward, done, info = real_env.step(action)
                    episode_reward += reward

                    state = next_state
                avg_reward += episode_reward
                # avg_success += float(info['is_success'])
            avg_reward /= config.eval_episodes
            # avg_success /= config.eval_episodes
            if avg_reward >= best_reward and config.save is True:
                best_reward = avg_reward
                agent.save_checkpoint(checkpoint_path, 'best')

            writer.add_scalar('test/avg_reward', avg_reward, total_numsteps)
            # writer.add_scalar('test/avg_success', avg_success, total_numsteps)

            print("----------------------------------------")
            print("Env: {}, Test Episodes: {}, Avg. Reward: {}".format(config.env_name, config.eval_episodes, round(avg_reward, 2)))
            print("----------------------------------------")

    # env.close() 

# python main.py --device 2

if __name__ == "__main__":
    arg = ARGConfig()
    arg.add_arg("env_name", "AntTransfer-v0", "Environment name")
    arg.add_arg("device", 0, "Computing device")
    arg.add_arg("policy", "Gaussian", "Policy Type: Gaussian | Deterministic (default: Gaussian)")
    arg.add_arg("tag", "default", "Experiment tag")
    arg.add_arg("start_steps", 1000, "Number of start steps")
    arg.add_arg("automatic_entropy_tuning", True, "Automaically adjust α (default: True)")
    arg.add_arg("seed", np.random.randint(0, 1000), "experiment seed")
    arg.parser()

    config = default_config
    config.update(arg)

    print(f">>>> Training OLBO on {config.env_name} environment, on {config.device}")
    train_loop(config, msg=config.tag)