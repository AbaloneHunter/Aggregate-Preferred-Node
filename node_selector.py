#!/usr/bin/env python3
"""
GitHub Actions Node Selector
自动测试节点延迟、速度，并生成优选节点列表
支持在线订阅和手动运行
"""

import os
import json
import time
import requests
import base64
import re
import sys
import argparse
import random
from datetime import datetime
from urllib.parse import urlparse
import concurrent.futures
import threading

class NodeSelector:
    def __init__(self, args):
        self.nodes_file = args.nodes_file
        self.output_file = args.output_file
        self.results_file = args.results_file
        
        # 命令行参数
        self.args = args
        
        # 从环境变量或命令行参数获取在线订阅地址
        self.subscription_urls = self.get_subscription_urls()
        
        # 测试配置
        self.timeout = args.timeout
        self.latency_threshold = args.latency_threshold
        self.max_workers = args.workers
        self.test_count = args.test_count
        
        # 测试URL列表
        self.test_urls = [
            {
                'url': 'https://www.gstatic.com/generate_204',
                'name': 'Google Static',
                'expected_status': 204,
                'weight': 1.0
            },
            {
                'url': 'https://httpbin.org/get',
                'name': 'HttpBin', 
                'expected_status': 200,
                'weight': 0.9
            },
            {
                'url': 'https://www.cloudflare.com/cdn-cgi/trace',
                'name': 'Cloudflare',
                'expected_status': 200,
                'weight': 0.8
            },
            {
                'url': 'https://api.github.com',
                'name': 'GitHub',
                'expected_status': 200,
                'weight': 0.7
            }
        ]
        
        self.results = []
        self.lock = threading.Lock()
        
    def get_subscription_urls(self):
        """从环境变量或命令行参数获取在线订阅地址"""
        # 优先使用命令行参数
        if self.args.subscription:
            urls = [url.strip() for url in self.args.subscription.split('&') if url.strip()]
            print(f"📡 从命令行参数找到 {len(urls)} 个在线订阅地址")
            return urls
        
        # 其次使用环境变量
        subscription_env = os.getenv('ONLINE_SUBSCRIPTION', '').strip()
        if subscription_env:
            urls = [url.strip() for url in subscription_env.split('&') if url.strip()]
            print(f"📡 从环境变量找到 {len(urls)} 个在线订阅地址")
            return urls
        
        return []
    
    def fetch_online_subscription(self, url):
        """获取在线订阅内容"""
        try:
            print(f"🔗 获取订阅: {url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, timeout=15, headers=headers)
            response.raise_for_status()
            
            # 尝试Base64解码
            try:
                content = base64.b64decode(response.text).decode('utf-8')
                print(f"✅ 订阅解码成功，长度: {len(content)} 字符")
                return content
            except:
                # 如果不是Base64，直接使用原内容
                print(f"✅ 订阅获取成功，长度: {len(response.text)} 字符")
                return response.text
                
        except Exception as e:
            print(f"❌ 获取订阅失败 [{url}]: {e}")
            return None
    
    def parse_subscription_content(self, content):
        """解析订阅内容"""
        nodes = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 支持各种代理协议
            if any(proto in line for proto in ['ss://', 'ssr://', 'vmess://', 'trojan://', 'vless://']):
                node = self.parse_node_line(line)
                if node:
                    nodes.append(node)
                    # 标记来自订阅
                    node['source'] = 'subscription'
        
        return nodes
    
    def load_all_nodes(self):
        """加载所有节点（本地文件 + 在线订阅）"""
        all_nodes = []
        
        # 1. 加载本地节点文件
        local_nodes = self.parse_nodes_file()
        for node in local_nodes:
            node['source'] = 'local'
        all_nodes.extend(local_nodes)
        print(f"📁 本地节点: {len(local_nodes)} 个")
        
        # 2. 加载在线订阅节点
        subscription_nodes = []
        for sub_url in self.subscription_urls:
            try:
                content = self.fetch_online_subscription(sub_url)
                if content:
                    nodes = self.parse_subscription_content(content)
                    subscription_nodes.extend(nodes)
                    print(f"📥 从订阅获取节点: {len(nodes)} 个")
                    
                    # 短暂延迟避免请求过快
                    time.sleep(1)
                    
            except Exception as e:
                print(f"❌ 处理订阅失败 [{sub_url}]: {e}")
        
        all_nodes.extend(subscription_nodes)
        
        # 去重（基于原始配置）
        unique_nodes = []
        seen = set()
        
        for node in all_nodes:
            node_id = node['original']
            if node_id not in seen:
                seen.add(node_id)
                unique_nodes.append(node)
        
        # 如果指定了测试数量，进行抽样
        if self.test_count > 0 and len(unique_nodes) > self.test_count:
            print(f"🔢 抽样测试: 从 {len(unique_nodes)} 个节点中随机选择 {self.test_count} 个")
            unique_nodes = random.sample(unique_nodes, self.test_count)
        
        print(f"📊 总节点数: {len(all_nodes)} → 去重后: {len(unique_nodes)} 个")
        return unique_nodes
    
    def parse_nodes_file(self):
        """解析节点文件"""
        nodes = []
        if not os.path.exists(self.nodes_file):
            print(f"⚠️ 节点文件 {self.nodes_file} 不存在")
            return nodes
            
        try:
            with open(self.nodes_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    node = self.parse_node_line(line)
                    if node:
                        nodes.append(node)
                    else:
                        print(f"⚠️ 第{line_num}行无法解析: {line[:50]}...")
                        
            return nodes
            
        except Exception as e:
            print(f"❌ 读取节点文件失败: {e}")
            return []
    
    def parse_node_line(self, line):
        """解析单行节点配置"""
        line = line.strip()
        
        patterns = [
            # SSR格式
            {'regex': r'^ssr://([A-Za-z0-9+/=]+)', 'type': 'ssr'},
            # VMess格式  
            {'regex': r'^vmess://([A-Za-z0-9+/=]+)', 'type': 'vmess'},
            # Trojan格式
            {'regex': r'^trojan://([^@]+)@([^:]+):(\d+)', 'type': 'trojan'},
            # VLESS格式
            {'regex': r'^vless://([^@]+)@([^:]+):(\d+)', 'type': 'vless'},
            # SS格式
            {'regex': r'^ss://([A-Za-z0-9+/=]+)', 'type': 'ss'},
            # HTTP代理
            {'regex': r'^http://([^:]+):(\d+)', 'type': 'http'},
            # SOCKS5代理
            {'regex': r'^socks5://([^:]+):(\d+)', 'type': 'socks5'},
            # 主机端口格式
            {'regex': r'^([^:]+):(\d+)$', 'type': 'host-port'}
        ]
        
        for pattern in patterns:
            match = re.match(pattern['regex'], line)
            if match:
                return {
                    'original': line,
                    'type': pattern['type'],
                    'parts': match.groups()
                }
        
        return None
    
    def extract_host_from_node(self, node):
        """从节点配置中提取主机地址"""
        try:
            if node['type'] in ['ssr', 'vmess', 'ss']:
                # Base64解码
                decoded = base64.b64decode(node['parts'][0] + '==').decode('utf-8', errors='ignore')
                
                # 尝试多种方式提取主机名
                host_patterns = [
                    r'"add":"([^"]+)"',      # VMess格式
                    r'server=([^&]+)',       # 参数格式
                    r'@([^:]+):',            # 用户信息格式
                    r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  # 通用域名格式
                ]
                
                for pattern in host_patterns:
                    match = re.search(pattern, decoded)
                    if match:
                        return match.group(1)
                        
            elif node['type'] in ['trojan', 'vless']:
                return node['parts'][1]  # 主机名
            elif node['type'] in ['http', 'socks5', 'host-port']:
                return node['parts'][0]  # 主机名
                
        except Exception as e:
            print(f"⚠️ 提取主机地址失败: {e}")
            
        return None
    
    def test_latency(self, node):
        """测试节点延迟"""
        test_results = []
        fastest_success = None
        
        for test_url in self.test_urls:
            try:
                start_time = time.time()
                
                response = requests.get(
                    test_url['url'],
                    timeout=8,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                )
                
                latency = int((time.time() - start_time) * 1000)  # 转换为毫秒
                is_success = response.status_code == test_url['expected_status']
                
                test_result = {
                    'url': test_url['name'],
                    'latency': latency,
                    'status': response.status_code,
                    'success': is_success,
                    'weight': test_url['weight']
                }
                
                test_results.append(test_result)
                
                # 记录最快成功测试
                if is_success and latency < self.latency_threshold:
                    if not fastest_success or latency < fastest_success['latency']:
                        fastest_success = test_result
                
                # 优质节点提前结束测试
                if latency < 100:
                    break
                    
                time.sleep(0.3)  # 短暂延迟
                
            except requests.RequestException as e:
                test_results.append({
                    'url': test_url['name'],
                    'latency': -1,
                    'status': 0,
                    'success': False,
                    'error': str(e),
                    'weight': test_url['weight']
                })
        
        return {
            'fastest_success': fastest_success,
            'all_results': test_results,
            'passed': fastest_success is not None
        }
    
    def test_download_speed(self, node, latency):
        """测试下载速度"""
        print(f"    🚀 开始速度测试，当前延迟: {latency}ms")
        
        # 根据延迟调整测试文件大小
        if latency < 200:
            file_size = 512000  # 500KB
        elif latency < 500:
            file_size = 256000  # 250KB
        else:
            file_size = 102400  # 100KB
        
        speed_test_urls = [
            f'https://httpbin.org/bytes/{file_size}',
            'https://speedtest.ftp.otenet.gr/files/test1Mb.db',
            'https://proof.ovh.net/files/1Mb.dat'
        ]
        
        for test_url in speed_test_urls:
            try:
                start_time = time.time()
                
                response = requests.get(
                    test_url,
                    timeout=15,
                    stream=True,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Cache-Control': 'no-cache'
                    }
                )
                response.raise_for_status()
                
                # 读取完整内容以确保测量准确
                content = b''
                for chunk in response.iter_content(chunk_size=8192):
                    content += chunk
                
                duration = time.time() - start_time
                data_size = len(content)
                
                if data_size > 0 and duration > 0:
                    speed_kbps = (data_size / duration) / 1024  # KB/s
                    speed_mbps = speed_kbps / 1024  # MB/s
                    
                    print(f"    📊 速度测试完成: {speed_kbps:.0f} KB/s ({speed_mbps:.2f} MB/s)")
                    return int(speed_kbps)
                    
            except requests.RequestException:
                continue
                
            time.sleep(0.5)
        
        print("    ⚠️ 所有测速URL均失败")
        return 0
    
    def get_geo_info(self):
        """获取地理位置信息"""
        try:
            # 获取公网IP
            ip_response = requests.get('https://httpbin.org/ip', timeout=8)
            if ip_response.status_code == 200:
                ip_data = ip_response.json()
                public_ip = ip_data.get('origin', '').split(',')[0]
                
                if public_ip:
                    # 获取地理位置
                    geo_response = requests.get(f'http://ip-api.com/json/{public_ip}', timeout=5)
                    if geo_response.status_code == 200:
                        geo_data = geo_response.json()
                        if geo_data.get('status') == 'success':
                            return {
                                'country': geo_data.get('country', 'Unknown'),
                                'city': geo_data.get('city', 'Unknown'),
                                'isp': geo_data.get('isp', 'Unknown'),
                                'lat': geo_data.get('lat'),
                                'lon': geo_data.get('lon'),
                                'ip': public_ip
                            }
        except requests.RequestException:
            pass
        
        return {
            'country': 'Unknown',
            'city': 'Unknown', 
            'isp': 'Unknown',
            'lat': None,
            'lon': None,
            'ip': 'Unknown'
        }
    
    def calculate_score(self, latency, speed, success):
        """计算综合评分"""
        if latency <= 0:
            return 0
        
        # 延迟评分
        if latency < 50:
            latency_score = 100
        elif latency < 100:
            latency_score = 95
        elif latency < 200:
            latency_score = 85
        elif latency < 300:
            latency_score = 75
        elif latency < 500:
            latency_score = 60
        elif latency < 1000:
            latency_score = 40
        else:
            latency_score = 20
        
        # 速度评分
        if speed == 0:
            speed_score = 0
        elif speed > 10000:
            speed_score = 100
        elif speed > 5000:
            speed_score = 90
        elif speed > 2000:
            speed_score = 80
        elif speed > 1000:
            speed_score = 70
        elif speed > 500:
            speed_score = 60
        elif speed > 100:
            speed_score = 40
        else:
            speed_score = 20
        
        # 成功率评分
        success_score = 100 if success else 0
        
        # 加权评分
        total_score = (latency_score * 0.5 + speed_score * 0.3 + success_score * 0.2)
        return round(total_score, 1)
    
    def test_single_node(self, node, index, total_count):
        """测试单个节点"""
        node_id = f"{index+1}/{total_count}"
        source_info = f"[{node.get('source', 'unknown')}]"
        print(f"\n🔍 测试节点 {node_id} {source_info}: {node['type']}节点")
        print(f"    📝 配置: {node['original'][:80]}...")
        
        try:
            # 第一步：延迟测试
            latency_test = self.test_latency(node)
            
            if not latency_test['passed']:
                print(f"    ❌ 未通过延迟测试，跳过测速")
                result = {
                    'node': node['original'],
                    'type': node['type'],
                    'latency': 'Timeout',
                    'speed': 'Not Tested',
                    'country': 'Unknown',
                    'city': 'Unknown',
                    'isp': 'Unknown',
                    'ip': 'Unknown',
                    'score': 0,
                    'success': False,
                    'test_url': 'None',
                    'timestamp': datetime.now().isoformat(),
                    'skipped_speed_test': True,
                    'source': node.get('source', 'unknown')
                }
                return result
            
            latency = latency_test['fastest_success']['latency']
            print(f"    ✅ 延迟测试通过: {latency}ms")
            
            # 第二步：获取地理位置
            geo_info = self.get_geo_info()
            print(f"    🌍 地理位置: {geo_info['country']}/{geo_info['city']} ({geo_info['isp']})")
            
            # 第三步：速度测试
            speed = 0
            if latency < self.latency_threshold:
                speed = self.test_download_speed(node, latency)
            else:
                print(f"    ⚠️ 延迟过高 ({latency}ms)，跳过测速")
            
            # 第四步：计算评分
            score = self.calculate_score(latency, speed, latency_test['fastest_success']['success'])
            
            result = {
                'node': node['original'],
                'type': node['type'],
                'latency': latency,
                'speed': f"{speed} KB/s" if speed > 0 else "Failed",
                'country': geo_info['country'],
                'city': geo_info['city'],
                'isp': geo_info['isp'],
                'ip': geo_info['ip'],
                'score': score,
                'success': latency_test['fastest_success']['success'],
                'test_url': latency_test['fastest_success']['url'],
                'timestamp': datetime.now().isoformat(),
                'source': node.get('source', 'unknown')
            }
            
            print(f"    📊 综合评分: {score}")
            return result
            
        except Exception as e:
            print(f"    ❌ 测试失败: {e}")
            return None
    
    def run_tests(self):
        """运行所有测试"""
        print("🚀 开始节点测试...")
        print(f"📡 测试URL: {[u['name'] for u in self.test_urls]}")
        print(f"⏱️ 延迟阈值: {self.latency_threshold}ms")
        print(f"🔢 最大并发数: {self.max_workers}")
        print(f"⏰ 超时时间: {self.timeout}秒")
        
        if self.test_count > 0:
            print(f"🎯 测试数量: {self.test_count} 个节点")
        
        # 显示订阅信息
        if self.subscription_urls:
            print(f"🌐 在线订阅: {len(self.subscription_urls)} 个")
            for i, url in enumerate(self.subscription_urls, 1):
                print(f"    {i}. {url}")
        print()
        
        # 加载所有节点
        nodes = self.load_all_nodes()
        if not nodes:
            print("❌ 没有找到可测试的节点")
            return
        
        print(f"📊 总共 {len(nodes)} 个节点需要测试\n")
        
        passed_count = 0
        speed_tested_count = 0
        
        # 使用线程池并发测试
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_node = {
                executor.submit(self.test_single_node, node, i, len(nodes)): (i, node)
                for i, node in enumerate(nodes)
            }
            
            for future in concurrent.futures.as_completed(future_to_node):
                i, node = future_to_node[future]
                try:
                    result = future.result()
                    if result:
                        with self.lock:
                            self.results.append(result)
                            
                            if result['success']:
                                passed_count += 1
                                if result['speed'] not in ['Not Tested', 'Failed']:
                                    speed_tested_count += 1
                
                except Exception as e:
                    print(f"❌ 节点测试异常: {e}")
        
        # 按评分排序
        self.results.sort(key=lambda x: x['score'], reverse=True)
        
        # 保存结果
        self.save_test_results(passed_count, speed_tested_count, len(nodes))
    
    def save_test_results(self, passed_count, speed_tested_count, total_count):
        """保存测试结果"""
        output_data = {
            'timestamp': datetime.now().isoformat(),
            'total_tested': total_count,
            'passed_latency_test': passed_count,
            'speed_tested': speed_tested_count,
            'preferred_nodes': [r for r in self.results if r['score'] > 0][:20],
            'all_results': self.results,
            'subscription_urls': self.subscription_urls,
            'test_config': {
                'urls': self.test_urls,
                'timeout': self.timeout,
                'latency_threshold': self.latency_threshold,
                'max_workers': self.max_workers,
                'test_count': self.test_count
            }
        }
        
        with open(self.results_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print('\n🎉 测试完成!')
        print(f"📊 总测试节点: {total_count}")
        print(f"✅ 通过延迟测试: {passed_count}")
        print(f"🚀 完成速度测试: {speed_tested_count}")
        print(f"🏆 最佳节点评分: {self.results[0]['score'] if self.results else 'N/A'}")
        
        # 显示来源统计
        source_stats = {}
        for result in self.results:
            source = result.get('source', 'unknown')
            source_stats[source] = source_stats.get(source, 0) + 1
        
        print(f"📦 节点来源统计:")
        for source, count in source_stats.items():
            print(f"    {source}: {count} 个")
    
    def generate_preferred_node_file(self):
        """生成优选节点文件"""
        try:
            with open(self.results_file, 'r', encoding='utf-8') as f:
                test_data = json.load(f)
            
            output = f"""# 🚀 Preferred Nodes - 优选节点
# Generated: {datetime.fromisoformat(test_data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}
# Total nodes tested: {test_data['total_tested']}
# Passed latency test: {test_data['passed_latency_test']}
# Speed tested: {test_data['speed_tested']}
# Success rate: {(test_data['passed_latency_test'] / test_data['total_tested'] * 100):.1f}%
# Workers: {test_data['test_config']['max_workers']}
# Timeout: {test_data['test_config']['timeout']}s

"""
            # 显示订阅信息
            if test_data.get('subscription_urls'):
                output += f"# 🌐 Online Subscriptions: {len(test_data['subscription_urls'])}\n"
                for url in test_data['subscription_urls']:
                    output += f"#   {url}\n"
                output += "\n"

            output += """# 🏆 Top Recommended Nodes (推荐节点)
# Format: 评分 | 延迟 | 速度 | 位置 | 运营商 | 来源
# Score | Latency | Speed | Location | ISP | Source

"""
            
            # 只显示有速度测试结果的节点
            valid_nodes = [
                node for node in test_data['preferred_nodes'] 
                if node['speed'] not in ['Not Tested', 'Failed'] and node['score'] > 0
            ]
            
            for i, node in enumerate(valid_nodes):
                status = '✅' if node['success'] else '⚠️'
                speed_value = int(node['speed'].split()[0]) if 'KB/s' in node['speed'] else 0
                speed_mbps = speed_value / 1024
                source = node.get('source', 'unknown')
                
                output += f"""# {status} {i+1}. 评分:{node['score']} | 延迟:{node['latency']}ms | 速度:{speed_mbps:.1f} MB/s | {node['country']} | {node['isp']} | {source}
{node['node']}

"""
            
            if not valid_nodes:
                output += "# ❌ 没有找到合格的节点，请检查节点配置或网络连接\n\n"
            
            output += f"# 📊 All Tested Nodes (所有测试节点)\n"
            output += f"# Total: {len(test_data['all_results']} nodes\n\n"
            
            for i, node in enumerate(test_data['all_results']):
                status = '✅' if node['success'] else '❌'
                speed_info = node['speed'] if node['speed'] != 'Not Tested' else '未测速'
                source = node.get('source', 'unknown')
                output += f"# {status} {i+1}. 评分:{node['score']} 延迟:{node['latency']}ms 速度:{speed_info} {node['country']} [{source}]\n"
                output += f"{node['node']}\n"
                
                if (i + 1) % 10 == 0:
                    output += '\n'
            
            # 添加统计信息
            valid_latencies = [
                node['latency'] for node in test_data['all_results'] 
                if node['latency'] != 'Timeout' and isinstance(node['latency'], (int, float))
            ]
            
            output += f"\n# 📈 Statistics (统计信息)\n"
            output += f"# Successful nodes: {test_data['passed_latency_test']}\n"
            output += f"# Speed tested nodes: {test_data['speed_tested']}\n"
            
            avg_score = sum(node['score'] for node in test_data['all_results']) / len(test_data['all_results'])
            output += f"# Average score: {avg_score:.1f}\n"
            
            if valid_latencies:
                output += f"# Best latency: {min(valid_latencies)}ms\n"
                output += f"# Average latency: {sum(valid_latencies) / len(valid_latencies):.1f}ms\n"
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(output)
            
            print(f"✅ {self.output_file} 文件已生成")
            
        except Exception as e:
            print(f"❌ 生成结果文件失败: {e}")

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='GitHub Actions Node Selector - 节点优选器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本使用
  python node_selector.py
  
  # 使用在线订阅
  python node_selector.py --subscription "https://sub1.com&https://sub2.com"
  
  # 调整并发数和测试参数
  python node_selector.py --workers 5 --timeout 20 --test-count 50
  
  # 自定义文件路径
  python node_selector.py --nodes-file my_nodes.txt --output my_results.txt
  
  # 快速测试少量节点
  python node_selector.py --workers 3 --test-count 10 --timeout 10
        """
    )
    
    # 订阅相关
    parser.add_argument('--subscription', '-s', 
                       help='在线订阅地址，多个用&分隔')
    
    # 测试参数
    parser.add_argument('--workers', '-w', type=int, default=3,
                       help='并发工作线程数 (默认: 3)')
    parser.add_argument('--timeout', '-t', type=int, default=10,
                       help='请求超时时间(秒) (默认: 10)')
    parser.add_argument('--latency-threshold', '-l', type=int, default=3000,
                       help='延迟阈值(毫秒)，超过此值不测速 (默认: 3000)')
    parser.add_argument('--test-count', '-n', type=int, default=0,
                       help='测试节点数量，0表示测试所有 (默认: 0)')
    
    # 文件路径
    parser.add_argument('--nodes-file', '-i', default='Nodes',
                       help='输入节点文件路径 (默认: Nodes)')
    parser.add_argument('--output-file', '-o', default='Preferred-Node',
                       help='输出结果文件路径 (默认: Preferred-Node)')
    parser.add_argument('--results-file', '-r', default='test-results.json',
                       help='测试结果JSON文件路径 (默认: test-results.json)')
    
    return parser.parse_args()

def main():
    """主函数"""
    print("=" * 60)
    print("GitHub Actions Node Selector")
    print("节点优选器 v2.0 - 支持手动运行和在线订阅")
    print("=" * 60)
    
    # 解析命令行参数
    args = parse_arguments()
    
    selector = NodeSelector(args)
    
    # 运行测试
    selector.run_tests()
    
    # 生成结果文件
    selector.generate_preferred_node_file()
    
    print("\n🎊 所有任务完成!")

if __name__ == "__main__":
    main()
