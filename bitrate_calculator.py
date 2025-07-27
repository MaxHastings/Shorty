class BitrateCalculator:
    def calculate_bitrate(self, size_mb, duration_sec, audio_bitrate_kbps_str, remove_audio_bool):
        print(f"\n--- BitrateCalculator Debug Input ---")
        print(f"Input Size MB: {size_mb}")
        print(f"Input Duration Sec: {duration_sec}")
        print(f"Input Audio Bitrate Choice: {audio_bitrate_kbps_str}")
        print(f"Input Remove Audio: {remove_audio_bool}")
        print(f"-------------------------------------\n")

        if duration_sec <= 0:
            raise ValueError("Duration must be positive to calculate bitrate.")
        
        # Convert MB to kilobits (1 MB = 8192 Kbits)
        # 1 MB = 1024 KB = 1024 * 8 Kbits = 8192 Kbits
        total_kbits = size_mb * 8192 
        print(f"Total target Kbits (raw): {total_kbits:.2f} Kbits")

        audio_bitrate_kbps = 0
        if not remove_audio_bool:
            try:
                audio_bitrate_kbps = int(audio_bitrate_kbps_str.replace('k', ''))
            except ValueError:
                audio_bitrate_kbps = 128 # Fallback if parsing fails
            print(f"Initial Audio Bitrate (from choice): {audio_bitrate_kbps} kbps")
        else:
            print("Audio will be removed.")

        # Account for potential overhead (container, metadata)
        # This is an estimation. Actual overhead can vary.
        overhead_factor = 0.08 
        target_kbits_for_streams = total_kbits * (1 - overhead_factor)
        print(f"Target Kbits for streams (after overhead factor): {target_kbits_for_streams:.2f} Kbits (accounting for {overhead_factor*100}% overhead)")

        min_audio_kbits_needed = audio_bitrate_kbps * duration_sec
        print(f"Minimum Kbits needed for audio: {min_audio_kbits_needed:.2f} Kbits")
        
        video_bitrate_kbps = 0

        if target_kbits_for_streams <= min_audio_kbits_needed:
            print("Scenario: Target size is too small for desired audio + default video.")
            min_video_bitrate_kbps = 50 # A reasonable minimum for video
            
            # Calculate max audio kbits possible given min video and total target
            max_audio_kbits_possible = target_kbits_for_streams - (min_video_bitrate_kbps * duration_sec)
            
            if max_audio_kbits_possible < 0:
                print("Even with minimum video bitrate, total Kbits budget is negative. Distributing proportionally.")
                # This means the target_kbits_for_streams is extremely low.
                # In this edge case, we'll just distribute what's available
                # Fallback to a very low, proportional distribution
                if duration_sec > 0:
                    audio_bitrate_kbps = max(0, int((target_kbits_for_streams * 0.3) / duration_sec))
                    video_bitrate_kbps = max(0, int((target_kbits_for_streams * 0.7) / duration_sec))
                else: # Should be caught by duration_sec <= 0 check, but as a safeguard
                    audio_bitrate_kbps = 0
                    video_bitrate_kbps = 0
            else:
                # Adjust audio down to fit the budget, ensuring minimum video bitrate
                audio_bitrate_kbps = int(max_audio_kbits_possible / duration_sec)
                # Ensure minimum audio bitrate if audio is kept and it's not being removed
                if audio_bitrate_kbps < 32 and not remove_audio_bool: 
                    audio_bitrate_kbps = 32
                print(f"Adjusted Audio Bitrate (to fit video min): {audio_bitrate_kbps} kbps")
                
                # Recalculate video kbits per second based on adjusted audio
                video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
                video_bitrate_kbps = max(min_video_bitrate_kbps, int(video_kbits_per_sec))
                print(f"Video Kbits per Second after audio adjustment: {video_kbits_per_sec:.2f}")

        else:
            print("Scenario: Target size is sufficient for desired audio and calculated video.")
            video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
            video_bitrate_kbps = max(50, int(video_kbits_per_sec)) # Ensure minimum video bitrate
            print(f"Video Kbits per Second (normal calculation): {video_kbits_per_sec:.2f}")

        # Final check for minimums
        if video_bitrate_kbps < 50: # Enforce a minimum video bitrate
            print(f"Warning: Calculated video bitrate {video_bitrate_kbps}kbps is below 50kbps. Capping at 50kbps.")
            video_bitrate_kbps = 50
        
        if not remove_audio_bool and audio_bitrate_kbps < 32: # Enforce a minimum audio bitrate if audio is present
            print(f"Warning: Calculated audio bitrate {audio_bitrate_kbps}kbps is below 32kbps. Capping at 32kbps.")
            audio_bitrate_kbps = 32

        print(f"\n--- BitrateCalculator Final Output ---")
        print(f"Calculated Video Bitrate: {video_bitrate_kbps} kbps")
        print(f"Calculated Audio Bitrate: {audio_bitrate_kbps} kbps")
        print(f"--------------------------------------\n")

        return video_bitrate_kbps, audio_bitrate_kbps
